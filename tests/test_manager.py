import json,sqlite3,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import manager as m
import tempfile
base=Path(tempfile.mkdtemp(prefix='context-handoff-test-'))
m.HOME=base.resolve()
m.DATA=base/'runtime'
tid=str(uuid4())
log=base/'rollout.jsonl'
con=sqlite3.connect(base/'state_5.sqlite')
con.execute('create table threads(id,source,archived,originator,project_id,rollout_path)')
con.execute('insert into threads values(?,?,?,?,?,?)',(tid,'vscode',0,'Codex Desktop',None,str(log)))
con.commit()
def state(project):
 (base/'.codex-global-state.json').write_text(json.dumps({'thread-project-assignments':{tid:{'projectKind':'local','projectId':project}} if project else {}}))
def record(n):
 log.write_text(json.dumps({'type':'event_msg','payload':{'type':'token_count','info':{'last_token_usage':{'total_tokens':n},'total_token_usage':{'total_tokens':999999},'model_context_window':10000}}}))
def call(event,**kwargs):
 return m.hook(dict(session_id=tid,hook_event_name=event,turn_id='test-turn',**kwargs))
state('project-A');record(5999);assert call('Stop')=={}
record(6000);assert 'project-A' in call('PostToolUse')['hookSpecificOutput']['additionalContext']
assert call('PostToolUse')=={}
assert call('Stop')['decision']=='block'
assert call('Stop',stop_hook_active=True)=={}
assert call('PreCompact',trigger='auto')['continue'] is False
assert call('PreCompact',trigger='manual')=={}
state(None);assert call('PreCompact',trigger='auto')=={}
with m.storage() as db: db.execute('insert into options values(?,1)',(tid,))
assert 'projectless' in call('UserPromptSubmit')['hookSpecificOutput']['additionalContext']
with log.open('a') as f:f.write('\n{"type":"compacted"}\n')
assert m.usage(log) is None
print("PASS threshold, cumulative exclusion, project, deduplication, compaction, manual opt-in, stale usage")

project_prompt = m.instruction(tid, "project-A")
assert "项目根目录的 handoff.md" in project_prompt
assert project_prompt.index("完整交接写入") < project_prompt.index("回读两份文件") < project_prompt.index("再用 create_thread")
assert "handoff.md" not in m.instruction(tid, None)
m.install()
hooks_path = m.HOME / "hooks.json"
original = hooks_path.read_bytes()
m.install()
assert hooks_path.read_bytes() == original
assert len(json.loads(original)["hooks"]) == 4
print("PASS handoff instructions and idempotent installation")
