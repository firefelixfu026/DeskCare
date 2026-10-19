# DeskCare M15–M18 迭代报告

日期：2026-10-18
项目：`E:\FelixFu\document\ZJU\2026AW\浙客松`
阶段：M15 主流程与异常处理、M16 数据闭环、M17 普通用户表达、M18 演示隔离与 Windows 交付

## 本轮做了什么

### M15｜主流程和异常处理

- 增补任务新增、编辑、删除（取消/确认）、导入预览取消/确认、语音草稿确认、文件读取失败和报告导出失败测试。
- 识别回来的语音只显示在草稿框；用户点“确认并添加”之前不保存任务。
- 修复导入预览表格在逐格填充期间即时校验读到空单元格并输出异常堆栈的问题。这个缺陷原先没有令 pytest 失败，因此在查看完整测试输出时进一步发现；已增加空行验证覆盖。
- 为真实显示提醒卡增加 UI 测试时，发现页面读取了不存在的 `explanation` 属性而领域对象字段为 `human_explanation`；已修复并覆盖完整提醒弹卡路径。
- 报告写入失败、任务清单无法读取时，向用户说明失败且不改动已有数据。

### M16｜数据一致性与提醒依据

- SQLite schema 升至 v7，提醒事件新增最小化 `decision_context_json`；已有 v6 提醒记录保留，迁移上下文为空。
- 提醒留痕包含规则版本、情境、活动授权/暂停、粗略活跃/空闲数据、最近切换、用户刚确认完成任务的信号、模糊截止剩余秒数、冷却和有效阈值。
- 明确不保留任务标题、应用名称、窗口标题、键盘内容、录音或精确截止时刻。
- 增强闭环自动化：CSV 导入并确认任务 → 模拟活动采集 → 策略提醒 → 用户反馈 → 完成任务 → 主动状态打卡 → 重开 SQLite → 验证报告事实一致。
- UI 把提醒内部规则码换成中文依据说明；未识别代码使用普通中文，不向用户显示策略常量。

### M17｜面向普通用户

- 导入错误、报告保存错误和轻量提醒优先说明“发生什么、现有内容是否保留、接下来可以做什么”。
- 新增非开发者独立走查清单，要求记录用户卡住的位置和原话。
- 真实用户理解测试尚未完成；开发者自评不视为可用性验收。

### M18｜演示数据隔离与交接

- `--demo` 改用单独的 `%LOCALAPPDATA%\DeskCare\demo\deskcare-demo.sqlite3`，正常模式仍使用原数据库；演示产生的模拟数据不会混入个人正式报告。
- 应用版本更新为 `2.0.0-m18`。
- 新增普通用户产品定位/架构说明、M15–M18 Windows 实机清单、M18 运行说明；README 与发布清单更新。
- Windows 11 / Python 3.12.7 / PyInstaller 6.22.3 构建 onedir 与 onefile，并生成 ZIP。两个 ZIP 解压到独立目录后，以临时 `LOCALAPPDATA` 启动模拟模式，均出现 DeskCare 主窗口且无未处理异常。
- M18 ZIP 校验值单独记录于 `release/DeskCare-M18-SHA256.txt`。未覆盖历史 M14 包。

## 测试结果

- 完整 pytest：收集 **110 项，109 passed、1 skipped**。
- 跳过项：`tests/test_m6_ai.py:121`，当前沙箱禁止本机 socket 探测；该跳过不代表真实本机 AI 服务通过。
- 定向任务/导入/UI 用例：**12 passed**；提醒卡与中文提示专项：**3 passed**；数据库/提醒/伙伴/端到端也随全量回归通过。
- `python -m compileall -q deskcare tests`：通过。
- `.venv` Python 3.12.7 的依赖检查：`pip check` 报告 `No broken requirements found`。
- `git diff --check`：通过（Git 提示 CRLF 自动转换警告；未报告空白错误）。
- onedir/onefile 两类解压 ZIP 独立启动验收通过，且包含提醒卡字段修复。构建产物未签名。

## 主要文件变化

- `deskcare/storage/database.py`：schema v7、提醒事件上下文持久化、演示数据库路径。
- `deskcare/services/reminder_service.py`：提醒最小输入上下文收集和中文摘要。
- `deskcare/app.py`：demo 数据库隔离、版本号更新。
- `deskcare/ui/pages.py`：提醒依据用户文案、任务导入/报告导出异常处理。
- `deskcare/ui/task_dialog.py`：导入预览未完整单元格保护。
- `tests/test_end_to_end_flow.py`、`tests/test_m1_storage.py`、`tests/test_m2_ui.py`、`tests/test_m8_companion.py`：迁移、闭环、UI、语音草稿与异常自动化。
- `PROGRESS.md`、`README.md`、`RELEASE_MANIFEST.md`：阶段状态和交付说明。
- `docs/M15-M18_阶段验收与Windows实机清单.md`、`docs/产品定位与技术架构.md`、`docs/M18_运行说明.md`：验收与产品/架构交接。

## 交付包

- 便携版：[DeskCare-M18-windows-x64-portable.zip](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-portable.zip)（78,277,470 bytes）
- 单文件版：[DeskCare-M18-windows-x64-onefile.zip](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-onefile.zip)（75,526,778 bytes）
- SHA-256：[DeskCare-M18-SHA256.txt](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-SHA256.txt)

推荐普通用户使用便携版，完整解压后运行内部的 `DeskCare-M18.exe`。程序不是安装器，且尚未代码签名；未提供自动更新。

## 尚未实现或未实机验证

- Windows 真实麦克风权限、语音模型识别质量和设备兼容性；无模型时语音不可用但手动输入正常。
- 真实托盘交互、锁屏/睡眠、100%/125%/150% 缩放、多显示器和另一台干净 Windows 机器。
- 非开发者学生/上班族可用性走查。
- Live2D 模型/动画目前没有实现；当前桌宠是 Qt 原生绘制的小芽圆形伙伴。
- 未接入云端语音或默认云 AI；没有发送真实 API 请求、没有保存真实 API Key。
- 未签名安装器、自动更新、临床验证、诊断、疗效或效率提升结论均不在本轮范围。

## 下一步

请先按 [M15–M18 Windows 实机清单](E:\FelixFu\document\ZJU\2026AW\浙客松\docs\M15-M18_阶段验收与Windows实机清单.md) 使用 M18 包走查核心任务和报告流，并告诉我普通用户是否看得懂、在哪一步停住。根据实际反馈再决定下一轮；在此之前不把尚未手测的内容写成“通过”。
