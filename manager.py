"""本地 Codex 桌面会话管理器，仅使用 Python 标准库。"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime
from uuid import UUID
import shutil

HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
DATA = HOME / "context-handoff"
EVENTS = ("PostToolUse", "Stop", "UserPromptSubmit", "PreCompact")


def desktop():
    db = sqlite3.connect((HOME / "state_5.sqlite").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def storage():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "control.sqlite", timeout=3)
    db.execute("create table if not exists options(id text primary key, enabled integer)")
    db.execute("create table if not exists signals(id text, turn text, event text, primary key(id,turn,event))")
    return db


def assignment(row, state):
    tid = row["id"]
    if tid in state.get("projectless-thread-ids", []):
        return None
    legacy = state.get("thread-project-assignments", {}).get(tid, {})
    if legacy.get("projectKind") == "local":
        return legacy["projectId"]
    project = row["project_id"]
    mapping = state.get("app-server-project-id-by-legacy-project-id-by-host", {}).get("local:" + str(HOME), {})
    return next((k for k, v in mapping.items() if v == project), project)


def usage(path):
    # Read backwards. Large tool responses may span several chunks.
    with Path(path).open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        tail = b""
        while pos:
            size = min(65536, pos)
            pos -= size
            f.seek(pos)
            lines = (f.read(size) + tail).split(b"\n")
            tail = lines.pop(0) if pos else b""
            for line in reversed(lines):
                if b'"token_count"' not in line and b'"compacted"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") == "compacted":
                    return None
                payload = record.get("payload", {})
                if record.get("type") == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    total = (info.get("last_token_usage") or {}).get("total_tokens")
                    capacity = info.get("model_context_window")
                    if isinstance(total, int) and total >= 0 and isinstance(capacity, int) and capacity > 0:
                        return min(total, capacity) * 100 / capacity
                    return None


def global_state():
    return json.loads((HOME / ".codex-global-state.json").read_text(encoding="utf-8"))


def enabled(db, tid, project):
    override = db.execute("select enabled from options where id=?", (tid,)).fetchone()
    return bool(override[0]) if override else bool(project)


def instruction(tid, project):
    if project:
        target = (
            f"用 list_projects 核对源项目 ID {project} 和项目根目录。"
            "先在项目中将本次完整交接写入 .handoffs/<源对话ID>/<唯一交接批次>/handoff.md，使用 UTF-8。"
            "再以项目根目录的 handoff.md 为入口。已有文件先备份，保留其他任务条目，"
            "仅新增或更新本对话的条目，写明源对话 ID、当前状态、下一步及本次交接文件的相对路径。"
            "回读两份文件确认保存成功，再用 create_thread 在同一项目 ID 下创建接手对话，environment.type=local。"
            "首条消息给出根目录 handoff.md 和本次交接文件的绝对路径、源对话 ID，"
            "要求先读项目入口，再按源对话 ID 读取本次交接，核实文件状态后继续。"
            "若入口被并发更新，按首条消息中的本次交接文件接手。"
            "若项目身份不明确或文件写入失败，保留现场并报告具体原因。"
        )
    else:
        target = "用 create_thread 在 projectless 下接手，首条消息附上交接摘要、原工作目录与文件的绝对路径。"
    return ("用户已启用 60% 自动交接。当前源对话 " + tid +
            " 已触发交接。若任务已全部完成或正等待用户输入，直接向用户交付或等待。"
            "若仍有自主工作，停在当前安全步骤，记录仍在运行的进程，不重复启动。"
            "将目标、用户最新要求、授权限制、文件绝对路径、Git状态、已验证项、未完成项和下一步写成精简交接内容。"
            + target + "创建前用 list_threads 查找标题标记 [接续-" + tid +
            "]，如已存在则复用。新对话标题必须包含此标记。让新对话核实工作目录、接手并执行下一步。"
            "若涉及不同工作树，先核实原工作树再修改。创建结果不确定时先核实，禁止盲目重试。"
            "核实新对话归属后，在旧对话给出新对话入口并结束旧任务。若有活动 Goal，按其真实状态处理并避免重复执行。")


def hook(data):
    event = data.get("hook_event_name")
    if event not in EVENTS or data.get("agent_id") or data.get("stop_hook_active"):
        return {}
    tid = str(UUID(data["session_id"]))
    with desktop() as source:
        row = source.execute("select * from threads where id=? and archived=0 and source='vscode'", (tid,)).fetchone()
    if not row or row["originator"] not in ("Codex Desktop", "codex_work_desktop"):
        return {}
    project = assignment(row, global_state())
    with storage() as db:
        if not enabled(db, tid, project):
            return {}
        if event == "PreCompact":
            if data.get("trigger") == "auto":
                return {"continue": False, "stopReason": "已阻止自动压缩。当前步骤暂停，原对话记录已保留。"}
            return {}
        pct = usage(row["rollout_path"])
        if pct is None or pct < 60:
            return {}
        turn = data.get("turn_id") or str(data.get("transcript_path", tid))
        if not db.execute("insert or ignore into signals values(?,?,?)", (tid, turn, event)).rowcount:
            return {}
    msg = instruction(tid, project)
    if event == "Stop":
        return {"decision": "block", "reason": msg}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}


def install():
    path = HOME / "hooks.json"
    config = json.loads(path.read_text("utf-8-sig")) if path.exists() else {}
    groups = config.setdefault("hooks", {})
    executable = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    command = f'{executable} -I -X utf8 "{Path(__file__).resolve()}" hook'
    HOME.mkdir(parents=True, exist_ok=True)
    changed = False
    for event in EVENTS:
        handlers = groups.setdefault(event, [])
        if not any(h.get("command") == command for g in handlers for h in g.get("hooks", [])):
            handlers.append({**({"matcher": "auto"} if event == "PreCompact" else {}), "hooks": [{"type": "command", "command": command,
                                        "timeout": 10, "statusMessage": "检查对话交接阈值"}]})
            changed = True
    if changed:
        if path.exists():
            shutil.copy2(path, path.with_suffix(".backup-" + datetime.now().strftime("%Y%m%d%H%M%S%f")))
        temp = path.with_name("hooks.context60." + str(os.getpid()) + ".tmp")
        temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")
        temp.replace(path)
    print("已登记交接钩子。请在桌面端查看并信任。")


def panel():
    import tkinter as tk
    from tkinter import ttk
    win = tk.Tk()
    win.title("Codex 对话交接 · 60%")
    tree = ttk.Treeview(win, columns=("project", "usage", "mode"), selectmode="browse")
    for key, title, width in [("#0", "最近的本地对话", 360), ("project", "项目", 120),
                              ("usage", "窗口已用", 90), ("mode", "自动交接", 90)]:
        tree.heading(key, text=title)
        tree.column(key, width=width)
    tree.pack(fill="both", expand=True)
    status = tk.StringVar()
    def refresh():
        selected = tree.selection()
        try:
            state = global_state()
            with desktop() as source, storage() as db:
                rows = source.execute("select * from threads where archived=0 and source='vscode' and originator in ('Codex Desktop','codex_work_desktop') order by updated_at desc limit 100")
                tree.delete(*tree.get_children())
                for row in rows:
                    project = assignment(row, state)
                    name = state.get("local-projects", {}).get(project, {}).get("name", project or "普通聊天")
                    try:
                        pct = usage(row["rollout_path"])
                    except OSError:
                        pct = None
                    tree.insert("", "end", iid=row["id"], text=(row["name"] or row["title"] or row["id"]).split("\n")[0], values=(
                        name, "未知" if pct is None else f"{pct:.1f}%", "开启" if enabled(db,row["id"],project) else "关闭"))
            if selected and tree.exists(selected[0]):
                tree.selection_set(selected[0])
            status.set("项目默认开启 · 普通聊天默认关闭 · 触发需要 Codex 已信任钩子")
        except Exception as exc:
            status.set(str(exc))
    def change(value):
        for tid in tree.selection():
            with storage() as db:
                db.execute("insert or replace into options values(?,?)", (tid,value))
        refresh()
    bar = ttk.Frame(win)
    bar.pack(fill="x")
    for label, action in [("开启所选对话", lambda: change(1)), ("关闭所选对话", lambda: change(0)), ("刷新",refresh)]:
        ttk.Button(bar,text=label,command=action).pack(side="left")
    ttk.Label(win,textvariable=status).pack(anchor="w")
    refresh()
    win.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("hook", "install", "panel"), default="panel", nargs="?")
    action = parser.parse_args().action
    if action == "install":
        install()
    elif action == "panel":
        panel()
    else:
        try:
            print(json.dumps(hook(json.load(sys.stdin))))
        except Exception as exc:
            print(json.dumps({"systemMessage": "60% 交接检查失败：" + str(exc)}))
