# 从零复刻与验收

本文对应仓库中的 manager.py。先运行合成数据测试，再安装到真实 Codex 环境，最后验证实际接手。下文所有占用率均指当前上下文窗口已使用比例。

## 1. 准备环境

准备 Windows 电脑、Git、Python 3.10+（建议 3.12）以及已登录的 Codex 桌面端。Python 安装时启用 tkinter 和 PATH。Git 与 Python 可通过各自官网安装：

- https://git-scm.com/downloads/win
- https://www.python.org/downloads/windows/

打开 PowerShell，检查命令能用。

~~~powershell
git --version
python --version
python -c "import sys, tkinter; print(sys.executable); print(tkinter.TkVersion)"
~~~

第三条应输出 Python 路径与 Tk 版本。如果 python 打开了应用商店，请先配置实际解释器的 PATH；如果提示找不到 tkinter，修改 Python 安装，补充 Tcl/Tk 组件。

工具依赖 Codex 自身提供模型访问和桌面工具。仅安装 Python 无法创建 Codex 对话。

## 2. 获取源码

公开仓库发布成功后，可执行以下命令。若仓库尚未创建，可使用本地交付的完整源码目录继续第 3 步。

~~~powershell
Set-Location $env:USERPROFILE
git clone https://github.com/PRICELESSymbol/codex-context-handoff.git
Set-Location ./codex-context-handoff
git status --short
git rev-parse HEAD
~~~

记录最后一条的提交号，以便他人复现相同版本。新克隆的仓库状态应为空。若目标目录已经存在，先进入并检查已有内容。

目录结构如下。

~~~text
codex-context-handoff/
  manager.py
  README.md
  docs/
    REPRODUCE.md
  tests/
    test_manager.py
  .github/
    workflows/
      tests.yml
  .gitignore
~~~

## 3. 先验证程序逻辑

在仓库根目录执行。

~~~powershell
python -B -X utf8 tests/test_manager.py
python manager.py --help
~~~

测试应退出为 0，并输出两行 PASS。中间会打印两次安装提示，安装目标是测试生成的临时目录。

测试读取合成的会话数据库与日志，覆盖以下情况。

| 输入或状态 | 期望行为 |
| --- | --- |
| 最近请求占用 59.99% | 不产生交接指令 |
| 最近请求占用 60% | 产生交接指令 |
| 累计用量很高，最近请求未达阈值 | 按最近请求判断 |
| 项目对话 | 默认启用 |
| 普通聊天 | 默认关闭，手动启用后可触发 |
| 同一对话、轮次、事件重复通知 | 抑制重复指令 |
| 已启用对话即将自动压缩 | 返回暂停请求 |
| 用户主动手动压缩 | 不拦截 |
| 日志末尾已有压缩事件 | 旧用量失效 |
| 项目交接指令 | 先保存并核验 handoff.md，再要求创建后继 |
| 连续安装两次 | 不重复添加相同命令的钩子 |

测试通过说明本地逻辑符合这些断言。真实模型遵循指令、新对话归属、实际钩子执行均需后续验证。

## 4. 核对真实 Codex 环境

先启动 Codex 桌面端。查找正在运行的配套程序，避免误用另一个独立安装的 CLI。

~~~powershell
Get-Process codex -ErrorAction SilentlyContinue |
  Select-Object Id, Path
~~~

从输出中找到桌面应用 resources 目录下的 codex.exe。复制它的完整路径，例如以 C:\Program Files\WindowsApps 开头的路径，然后执行下面的命令，替换占位内容。

~~~powershell
$desktopCodex = '这里替换成上一步的 codex.exe 完整路径'
& $desktopCodex --version
~~~

本项目原始检查版本为 0.167.0-alpha.3.2。其他版本需通过本指南验证，不能仅凭版本号认定兼容。

默认配置目录为用户目录下的 .codex。如果你专门设置过 CODEX_HOME，安装程序和面板必须在相同设置下运行。

~~~powershell
$codexData = Join-Path $env:USERPROFILE '.codex'
if ($env:CODEX_HOME) { $codexData = $env:CODEX_HOME }
Test-Path (Join-Path $codexData 'state_5.sqlite')
Test-Path (Join-Path $codexData '.codex-global-state.json')
~~~

当前实现依赖这两个文件。出现 False 时，先确认桌面启动、登录与配置位置，再安装。

## 5. 注册与信任钩子

在准备长期保留的源码目录中执行。

~~~powershell
python -X utf8 manager.py install
~~~

安装程序将当前解释器和源码绝对路径写入 hooks.json。已有 hooks.json 会备份到同目录，文件名包含 backup 与时间。它会保留已有其他钩子，并添加以下四项。

| 钩子 | 用途 |
| --- | --- |
| UserPromptSubmit | 用户发消息时检查 |
| PostToolUse | 工具调用后检查 |
| Stop | 本轮准备结束时检查，必要时要求继续交接 |
| PreCompact，matcher 为 auto | 自动压缩前请求暂停 |

使用第 4 步确定的配套 CLI。

~~~powershell
& $desktopCodex
~~~

在交互界面输入 /hooks，找到命令指向本仓库 manager.py 且以 hook 结尾的四项，查看并信任。若当前版本没有此菜单或不识别四种事件，记录版本与错误，停止安装验收。

信任是 Codex 自身的审核步骤。安装脚本打印成功不代表已经信任，也不代表已经被现有桌面对话加载。等待正在运行的任务到达结束点，再重新打开桌面端。

同一电脑若已安装旧路径版本，请先禁用旧路径四项，避免多个脚本同时产生指令。重复安装相同命令是幂等操作，换路径会生成不同命令。

## 6. 打开管理面板

~~~powershell
python -X utf8 manager.py panel
~~~

观察窗口中的对话标题、项目、占用率、启用状态。点击刷新重新读取状态。它显示最近 100 个符合本机桌面来源条件的未归档对话。

项目对话默认启用，普通聊天默认关闭。可以选择一行单独开启或关闭。手动选择会持久保存，覆盖默认规则。当前版本没有恢复默认按钮；再次选择开启或关闭即可调整。

面板关闭不会停用钩子。它不需要注册开机启动服务。钩子随 Codex 事件调用，因此闲置且没有新事件的聊天不会被主动唤醒。

## 7. 复现项目 handoff.md 交接

在 Codex 桌面端建立一个独立测试项目，目录中放置简单的练习资料。先用短任务确认该项目内能使用 list_projects、list_threads、create_thread。

正式的阈值复现需要该测试对话自然增长到至少 60%。当前版本未提供“模拟真实桌面用量”开关。不要把合成日志的测试结果记录成真实桌面交接。

给测试对话安排连续、有明确未完成项的工作，在面板中刷新观察占用。达到阈值后，等待下一次支持的生命周期事件，并记录以下证据。

1. 源对话收到交接指令，保存本次专属交接文件。
2. 项目根目录 handoff.md 已备份并更新，包含源对话 ID 和本次记录路径。
3. 新对话出现在原 Codex 项目下，项目 ID 一致。
4. 新对话首条消息提供根入口与专属记录的绝对路径。
5. 新对话读取记录后实际执行第一项未完成工作。
6. 源对话结束交接，没有同时继续修改同一任务文件。

专属记录的示例路径如下。

~~~text
项目目录/
  handoff.md
  .handoffs/
    <源对话ID>/
      <唯一交接批次>/
        handoff.md
~~~

交接文件建议按下面的结构填写。该模板说明交接指令要求的内容，实际文件由源对话写入。

~~~markdown
# 任务交接

更新时间、源对话 ID、项目 ID、实际工作目录

## 目标与用户要求

当前目标、最新补充、授权范围、验收条件

## 已完成

修改文件及绝对路径、有效版本、验证命令与结果

## 当前现场

Git 状态、未提交改动、运行中的进程、输出位置

## 未完成与风险

待执行项、已知失败、外部依赖

## 下一步

接手后首先核实什么，接着执行什么
~~~

根入口是多任务的索引。独立记录用于让并行任务找到自己的现场。当前代码以模型指令要求保留其他条目，没有文件锁，并发更新根入口仍存在覆盖风险。

## 8. 理解触发时机

计算公式为 min(last_token_usage.total_tokens, model_context_window) / model_context_window × 100%。

例如最近一次请求记录 60,000 tokens，有效窗口为 100,000，结果为 60%。total_token_usage 的累计值不参与这一计算。

工具在事件边界检查，可能看到 58% 后直接变成 64%。当工具输出很大、模型一次请求占用突增，或钩子尚未加载时，不能保证恰好在 60.00% 接手。

PreCompact 的暂停是防止自动压缩的兜底。当这条路径先发生，任务可能停住，需要人工继续；它不会自行创建接手对话。

当前任务已经全部完成，或者正在等待用户输入时，交接指令允许源对话交付结果或等待。

## 9. 排错

| 现象 | 核查路径 |
| --- | --- |
| 没有显示对话 | 检查配置目录、数据库文件、桌面是否登录；当前面板有来源与未归档过滤 |
| 占用率显示未知 | 等待一次模型请求完成并刷新，确认日志中有 token_count |
| 超过 60% 还没交接 | 检查该对话开关、四个钩子的信任状态、桌面是否重新加载、是否已有后续事件 |
| 完成任务后没有创建新聊天 | 检查是否确实还有未完成工作 |
| 新对话创建失败 | 检查源会话的桌面工具能力、项目 ID 及创建工具错误 |
| 被暂停但没有自动接手 | 检查是否先触发了 PreCompact 兜底 |
| 重复出现交接指令 | 检查是否注册了多个不同路径版本；不同事件也可能分别提示 |
| Python 路径错误 | 用新解释器重新安装并信任，停用旧命令 |
| 界面缺少中文或出现乱码 | 使用 UTF-8 保存文件并以 -X utf8 运行 |
| Codex 更新后报字段错误 | 记录版本与脱敏错误，检查本工具依赖的内部数据结构 |

提交问题时附上系统版本、配套 CLI 版本、Python 版本、复现步骤、实际结果、预期结果。请先脱敏任务正文、身份凭据和个人路径。

## 10. 更新、停用与恢复

更新前保留当前提交号。等待任务结束，在干净工作区执行 git pull --ff-only，运行测试后再使用。源码路径发生变化需重新安装并审核命令。

停用时，在 /hooks 中禁用命令指向本工具的四项。随后重新加载桌面配置。已有交接记录和开关数据库可以保留用于回查。

安装备份位于 Codex 配置目录中的 hooks.backup-<时间>。恢复前比较当前文件与备份，因为其他插件可能在安装之后添加过自己的配置。只撤回本工具条目通常更容易保留后续配置。

## 11. 验证状态与复现报告

| 验证层级 | 本项目目前记录 |
| --- | --- |
| 合成数据与指令生成 | 已通过本地回归 |
| 幂等安装 | 已通过临时目录测试 |
| 桌面同项目创建后继对话并完成小任务 | 已独立实测 |
| 新版 handoff.md 流程真实读写 | 尚未完成桌面端到端验收 |
| 达到 60% 后经已信任钩子自动接手 | 尚未完成端到端验收 |
| GitHub Actions | 工作流已提供，远程结果以仓库运行记录为准 |

复现报告至少填写源码提交号、Python 与 Codex 版本、触发前后占用率、源与目标项目 ID 是否一致、handoff.md 是否读取、接手后第一步结果，以及旧对话是否仍在运行。对未经实际执行的环节标注“未验证”。
