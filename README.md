# DeskCare

[Windows 体验版下载](https://github.com/firefelixfu026/DeskCare/releases/tag/v2.0.0-ui19) · [悬浮窗三态任务](docs/UI19_悬浮窗三态任务.md) · [日报复盘](docs/UI18_日报复盘与任务防误触.md) · [历史版本归档](https://github.com/firefelixfu026/DeskCare/releases/tag/legacy-archive-2026-10-21) · [商业计划书](docs/DeskCare_商业计划书_UI13.md)

DeskCare 是一个 Windows 本地优先的数字健康习惯辅助与今日任务联动工具。它不是医疗诊断器、生产力评分器或全天候行为监视器。

## 当前开发阶段：UI19 悬浮窗三态任务

当前程序：`dist/DeskCare-UI19/DeskCare-UI19.exe`，项目根目录 `Start-DeskCare.cmd` 指向最新版；本机保留完整程序，不要求重复下载。先从托盘退出旧版。悬浮任务右侧沿用主页面的“待处理／进行中／已完成”圆角菜单，选中即保存，不再弹完成确认框；打开、浏览、取消不保存，标题仍只查看。菜单与详情匹配置顶层级。见 [UI19 说明](docs/UI19_悬浮窗三态任务.md)。保留 UI18 日报复盘的独立授权、中文预览与最小数量上传，以及其他既有功能。

“轻量个人 AI 健康助手”将任务与使用节奏、主动状态记录、检验单辅助阅读放在个人桌面。每个敏感功能独立授权，不自动混合或上传健康历史。检验单辅助阅读从血常规常见项起步，不作疾病或治疗判断。

UI8 将任务安排日期、截止时间、活动时段、用户备注分开保存；保护原清单中的日期与时间，AI 只在缺少预计用时的情况下给出可修改建议。今日／后续／全部任务与应用排行使用自适应分页。使用统计支持每天／日历周和历史翻看，另可独立开启按小时的类别时长汇总；默认关闭，不回填旧小时数据，关闭即清除小时记录。提醒间隔可手动输入 1–180 的任意整数分钟。

UI2 在 UI1 五项左侧导航（今日任务、使用统计、状态打卡、日报与周报、设置与隐私）的基础上，统一浅色弹窗和无原生黑框的下拉/数字控件，图表从上一帧平滑过渡，状态页增加近七天自主记录，并简化桌面伙伴、移除内置语音输入。应用数据和独立授权规则保持原有语义。UI3 新增简洁面板/吉祥物切换，三种表情只对应今天主动保存的状态打卡，并使用独立拖动和左右贴边图。新包说明见 `docs/UI3_使用说明.md`。

UI4/UI5 整理任务列表与状态菜单；UI6 改善日报行距、阅读宽度和文案，并补齐简洁面板右键切换吉祥物的入口。UI7 新增独立桌面提醒、无记录预览和提醒状态，兼容 DeepSeek 根地址及清晰的网络错误分类。UI7 的五分钟步进间隔已在 UI8 改为可手动输入。旧版本和 UI6 参赛快照保留，最新进展以 `PROGRESS.md` 为准。真实 AI 效果仍需用户清单对照验收，不把接口实现当成准确性证明。

DeskCare 已实现 M0–M18 的代码阶段工作，包括 XLSX 清单导入、贴边圆形伙伴、任务/提醒/报告闭环和演示数据隔离。M15–M18 自动化回归已覆盖新增数据留痕与异常路径；本轮 Windows 新发布包和真实设备验收以 `PROGRESS.md` 的最新记录为准。真实模型/API、不同 DPI/多屏和普通用户可用性仍需实机验收。

- “今日任务”“使用统计”“状态打卡”“日报与周报”“设置与隐私”左侧导航；
- 系统托盘打开、暂停监测、退出；没有系统托盘时回退到可见窗口退出；
- 首次启动活动监测、应用明细、健康打卡、本地 AI 和提醒反馈个性化均默认关闭；
- 使用明确标注的演示数据；
- 使用 `assets/deskcare-app-icon.png` 作为应用/托盘图标，缺失时自动回退到代码绘制图标；
- Windows 受控采样：仅在用户明确开启后读取空闲秒数和粗粒度应用类别，不读取窗口标题或键盘内容；
- 使用 `monotonic` 间隔估算活动/空闲/未知时段，超过 60 秒的间隔不计入活动；
- 显示当前连续活跃会话估计，遇到空闲、未知、暂停、异常或长间隔立即截断；
- SQLite 增量迁移保存独立同意状态和按日类别聚合；应用明细需另行授权，只保存规范化进程名和每日活跃时长，不保存完整路径；
- 使用统计页提供所选日／周的应用累计时长；撤回应用明细授权会清除已保存的应用级数据；小时类别汇总使用独立开关；
- 休息提醒可显示可关闭、可跳过的轻柔活动建议，不作医学判断或疗效承诺；
- 可在设置或托盘显式开启桌面伙伴；默认隐藏、可拖动/隐藏；拖到屏幕左右边缘会收成小芽吉祥物半露状态，点击即可展开；提供任务快速添加、详情查看、独立三态选择和情境选择；
- UI2 按用户反馈移除内置语音转文字、录音、模型选择及 Vosk 依赖；桌面伙伴只保留任务与情境操作，不访问麦克风；
- 设置页支持经确认后清除已保存的活动聚合，不偷偷改变监测授权；
- 今日页支持手工添加、编辑、删除和状态修改；
- 支持用户主动选择 `.txt` / `.md` / `.csv` / `.xlsx` 文件，先生成可编辑任务草稿预览，再由用户确认入库；
- 文本导入支持 UTF-8/BOM、Markdown 清单、保守的时间与预计时长提示；CSV/XLSX 使用严格列校验和 ISO 日期格式；XLSX 仅读取第一个工作表值，不执行公式；
- 导入限制文件大小、行长度和任务数量，错误列名、损坏 CSV、空文件、重复标题和模糊时间会在确认前明确显示；
- SQLite v2 增量迁移保存已确认任务，不保存源文件路径或原文；取消预览不会写入任务库；
- 用户输入的无时区 ISO 截止时间按本地民用时间保存为带时区值，避免跨模块比较异常；
- M3 规则提醒结合已确认任务、有限活动和用户情境，使用非阻断卡片与本地反馈冷却；
- M4 BodyLog 独立授权、粗粒度用户自报、按日覆盖/缺失数据的 FactSheet，以及本地模板日报/周报；
- 报告可在界面查看并由用户主动导出 Markdown；没有状态授权时明确显示缺失，不提供健康判断；
- 单实例运行：第二次启动只请求已有窗口显示，不会重复采样或打开第二份数据库连接；
- 设置页提供带二次确认的全部本地数据清除，包含授权状态、活动、任务、提醒和 BodyLog；
- `scripts/build_windows.ps1` 提供 Windows PyInstaller onedir 构建入口，`scripts/run_baseline.py` 提供可复现的合成策略对照；
- pytest 覆盖默认配置、暂停门控、模拟 provider、四页窗口、SQLite 迁移、跨午夜分桶、长间隔、应用明细授权和聚合、提醒策略、BodyLog、报告事实、桌宠贴边和 XLSX 导入（最新数量见 `PROGRESS.md`）。
- M6 提供可选的本地 Local LLM 任务候选解析和 FactSheet 报告改写：任务只处理用户主动选择的单个任务文件，报告只在用户主动点击后处理当前结构化事实；只允许访问 `localhost` / `127.0.0.1` / `::1`，输出必须经过结构化校验；不可用时自动回到规则/模板。
- 本地模型候选不会绕过预览和确认，不保存原文或原始模型响应；本地 AI 授权默认关闭，并与活动监测、BodyLog 独立。
- 本地 AI 的 endpoint 和模型名可在“设置与隐私”中修改并保存到 SQLite；保存只做格式校验，不联网测试；“清除全部本地数据”会一并删除这些配置。
- 设置页提供用户主动触发的“检测本机模型”：后台只请求回环服务的 `/api/tags`，不发送任务、报告或 BodyLog，并区分服务离线、在线但无模型、配置模型可用/不匹配。
- 报告页的本地 AI 改写在后台线程执行，模型响应慢或不可用时不会阻塞主窗口，并自动回退到模板报告。
- 任务预览中的“本地 AI 提议”同样在后台执行；等待时保留规则草稿，取消预览会使迟到模型结果失效，模型响应永远不能绕过人工确认。
- 退出应用时会等待当前有界本机模型请求结束后再销毁 Qt 工作线程，避免请求进行中退出造成异常终止。
- Local AI 请求使用禁用代理的回环直连 opener；即使系统开启 Clash/HTTP(S)_PROXY，也不会把本地模型请求转发到代理或外网。
- 提醒反馈建议使用独立授权且默认关闭，演示反馈不参与；最近至多 30 条回应中，至少 10 条总体、同情境 5 条且不合适占比 ≥40% 时建议用户检查间隔，不自动修改。暂不调整／采纳后等 5 条新的同情境反馈再提示。可主动让 AI 分析任务和最小情境快照，另有独立许可、逐次预览确认和严格输出校验；没有 AI 仍按规则正常提醒。

接口与边界位于 `deskcare/importers/`、`deskcare/ai/`、`deskcare/services/task_service.py`、`deskcare/sensors/base.py`、`deskcare/services/reminder_service.py`、`deskcare/services/personalization_service.py`、`deskcare/services/bodylog_service.py` 和 `deskcare/services/report_engine.py`；M4 本地模板仍是可靠兜底，M6 的 AI 只辅助任务候选和用户主动触发的 FactSheet 文案改写。

联网 AI 支持逐次确认的任务清单整理，以及 UI11 另行授权的提醒快照分析；两条权限不互相继承。不会后台上传屏幕、应用轨迹、打卡历史或不适记录，不做医学判断、自动任务完成或应用锁。Windows provider 仅在 Windows 实例化；其他环境使用明确标记的 FakeProvider。应用不内置或下载模型，没有 AI 时离线核心功能仍可用。

## 运行

建议使用 Python 3.11 或 3.12：

```powershell
python -m pip install -e ".[dev]"
python -m deskcare
```

UI2 不含语音输入组件，不需要安装或选择语音模型。可直接输入任务；如使用系统听写，由 Windows 自身的设置和隐私规则管理，DeskCare 不调用麦克风。旧版语音文档仅作历史记录。

比赛演示或离线回归时，可以显式使用模拟 provider；模拟数据会在界面中标注，且仍需手动开启活动统计。演示模式使用单独数据库 `%LOCALAPPDATA%\DeskCare\demo\deskcare-demo.sqlite3`，不会混入日常活动报告：

```powershell
python -m deskcare --demo
```

如需直接展示完整产品闭环（虚构任务、模拟活动、休息提醒和反馈、主动状态记录、日报），使用 `python -m deskcare --demo-scenario`。完整流程写入按日期隔离的单独演示库，主窗口和报告均会明确标注数据为虚构；不访问网络、AI 或真实活动 provider。重复启动不会重复生成当天示例。

如果 Windows 上的 pip 因代理或 PyPI SSL 问题无法下载 `setuptools` 构建依赖，可以绕过 editable 构建，直接安装运行/测试依赖；在项目根目录运行时不需要先安装 DeskCare 包：

```powershell
$proxy = "http://127.0.0.1:7897"
$env:HTTP_PROXY = $proxy
$env:HTTPS_PROXY = $proxy
python -m pip install --proxy $proxy -r requirements-dev.txt
python -m deskcare
python -m pytest -q
```

如果你的 Clash Verge 使用的混合端口不是 `7897`，请把命令中的端口替换为 Clash Verge“端口设置”中的实际值。

### Windows 构建与卸载

开发/测试依赖（包含 PyInstaller）：

```powershell
python -m pip install -r requirements-dev.txt
```

在项目根目录构建不需要安装器的 onedir 包：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

构建后自动启动隔离的演示实例并检查主窗口、Qt DLL 和异常弹窗：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -Verify
```

产物为 `dist\DeskCare\DeskCare.exe`。将整个 `dist\DeskCare` 文件夹复制到目标电脑即可运行；不要只复制 exe，因为 Qt 和资源文件位于同一目录。卸载时先退出托盘中的 DeskCare，再删除整个 `dist\DeskCare` 文件夹和用户数据目录 `%LOCALAPPDATA%\DeskCare`（删除前请确认不再需要本地任务/报告）。应用内“清除全部数据”会使用 SQLite `secure_delete` 并尝试压缩数据库，但这不是法证级擦除，系统备份或磁盘快照仍可能保留副本。应用没有后台服务、自动启动或云端账户。

构建脚本会临时隔离 PATH，只使用指定虚拟环境的 Python 和系统目录。这样可以避免电脑同时安装 Python 3.12/3.14 或多个 Qt 发行版时，PyInstaller 收集到错误的 `python3.dll`/Qt 依赖。

如果必须交付单个文件，可以使用实验性的 onefile 变体：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -OneFile
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -OneFile -Verify
```

它会生成 `dist\DeskCare.exe`。看到“QtCore.dll 找不到指定的程序”时，先用项目脚本重新构建，不要混用不同构建目录的 exe 与 `_internal`；onedir 仍必须复制整个 `dist\DeskCare` 文件夹，onefile 才可以单独复制。

也可以单独验证已有产物。验证脚本会拒绝已有同路径进程，使用临时 `LOCALAPPDATA`，并在结束时只停止本次启动的进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_windows_package.ps1 -Executable .\dist\DeskCare\DeskCare.exe
powershell -ExecutionPolicy Bypass -File .\scripts\verify_windows_package.ps1 -Executable .\dist\DeskCare.exe
```

### 已验证发布 ZIP

`release\DeskCare-UI3-windows-x64-portable.zip` 是本轮界面更新的便携交付物；完整解压后，进入内层 `DeskCare-UI3` 文件夹运行 `DeskCare-UI3.exe`。本轮先做离屏验证，再获用户授权完成独立演示实例的部分实机走查；三种表情与任务联动已验证，贴边/快捷键盘/托盘等剩余项见 UI3 报告。SHA-256 见 `release/DeskCare-UI3-SHA256.txt`。M18r1 和更早版本保留供追溯；源码仓库为 [DeskCare GitHub 仓库](https://github.com/firefelixfu026/DeskCare)，本轮远端同步状态请看 `PROGRESS.md`，不要把本地完成等同于已推送。

```powershell
Get-FileHash -Algorithm SHA256 .\release\DeskCare-UI3-windows-x64-portable.zip
```

### 可复现策略对照

```powershell
python .\scripts\run_baseline.py
```

输出只使用虚构情境，比较固定 40 分钟提醒与 DeskCare 情境策略的动作和 reason code，不宣称健康或效率优越性。

测试：

```powershell
pytest -q
```

关闭主窗口时，若系统托盘可用，应用会隐藏到托盘；右键托盘可以重新打开、暂停/恢复监测或退出。首次启动不读取 Windows 活动，也不访问用户文件或网络。

## 隐私边界

监测只有在用户明确开启后才允许 provider 读取样本；暂停后立即停止读取。非 Windows 环境使用合成模拟 provider，所有演示数字和任务均明确标注为演示数据。

完整产品、技术和隐私约束见 `README_先看我.md` 与 `docs/`。M4 的 BodyLog 与活动监测、任务管理均为独立授权；M5 增加单实例、可清除数据和 Windows 构建；M6 增加可选本地 AI 任务候选链路，但真实模型是否可用仍以本机人工验证为准。

M15–M18 阶段验收、Windows 实机检查与尚未实测边界见 `docs/M15-M18_阶段验收与Windows实机清单.md`；产品定位与当前架构见 `docs/产品定位与技术架构.md`；常见问题排查见 `docs/Windows_常见问题与故障排查.md`。旧版 M10/M11 清单仅记录当时阶段，后续范围以新清单为准。

历史 M1 演示流程见 `docs/M1_演示脚本.md`，M2 演示流程见 `docs/M2_演示脚本.md`，M2 验收记录见 `docs/M2_验收记录.md`，Windows 人工验收清单见 `docs/M2_Windows人工验收清单.md`。
M3 演示流程见 `docs/M3_演示脚本.md`，M4 演示流程见 `docs/M4_演示脚本.md`，M4 验收记录见 `docs/M4_验收记录.md`。
M5 验收记录见 `docs/M5_验收记录.md`，M5 演示流程见 `docs/M5_演示脚本.md`，Windows 清单见 `docs/M5_Windows人工验收清单.md`。
M6 验收记录见 `docs/M6_验收记录.md`，M6 演示流程见 `docs/M6_演示脚本.md`，Windows 清单见 `docs/M6_Windows人工验收清单.md`。

