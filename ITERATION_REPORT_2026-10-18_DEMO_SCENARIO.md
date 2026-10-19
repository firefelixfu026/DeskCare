# DeskCare 迭代报告：完整离线演示闭环

日期：2026-10-18（Asia/Shanghai）
项目：`E:\FelixFu\document\ZJU\2026AW\浙客松`

## 本轮目标与结论

复核 M18 演示体验后发现，原有 `--demo` 仅提供空白模拟数据库与模拟活动，并不能直接讲清任务、提醒、状态回顾和报告之间的完整关系。本轮补齐脚本化的完整演示场景，确保模拟数据隔离且在界面和导出报告中明确标识；重新构建 Windows 包并对压缩包解压后的应用进行启动验收。

## 已完成

- 新增 `python -m deskcare --demo-scenario`：启动时一次性生成两项示例任务、一段约 40 分钟虚构活动、一次休息提醒及用户反馈、一条用户主动填写的状态记录，以及对应的本地日报。
- 场景调用现有导入、任务、活动采集、提醒反馈、状态记录和报告服务；不读取操作系统活动、不请求网络、不调用 AI。
- 演示库按本地日期单独存放，并带幂等标记；同一天重复启动不会再次插入示例记录。空白 `--demo`、完整场景和正式用户数据库互相隔离。
- 主窗口所有页面顶部增加演示提示；日报标题与正文也说明其内容是虚构的、不是本机真实记录，不能用于判断健康状况或证明产品效果。
- 增加场景完整性、幂等性、数据库隔离测试，以及主界面演示提示测试。
- 更新 `PROGRESS.md`、README、M5 演示脚本、M18 运行说明、发布清单和 ZIP 哈希文件。
- 重新构建 onedir 便携版和 onefile 单文件版；两个新 ZIP 分别解压后均通过 `--demo-scenario` 启动检查。

## 验证结果

- 全量自动化测试：**112 项，111 passed、1 skipped**。唯一跳过项是当前沙箱禁止本机 socket 探测的本地模型连接测试；它不代表真实模型已验收。
- `python -m pip check`：`No broken requirements found`。
- `python -m compileall -q deskcare tests scripts`：通过。
- onedir、onefile 的 PyInstaller 构建及构建后启动检查：通过。
- 两个已打包 ZIP 均在独立目录解压，并使用临时用户数据目录以 `--demo-scenario` 启动通过。此检查验证启动过程，不等于逐页人工体验或真实用户环境验收。

## Windows 交付包

- 推荐便携版：[DeskCare-M18-windows-x64-portable.zip](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-portable.zip)（78,279,900 bytes）
- 单文件备选版：[DeskCare-M18-windows-x64-onefile.zip](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-onefile.zip)（75,531,578 bytes）
- SHA-256 清单：[DeskCare-M18-SHA256.txt](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-SHA256.txt)
- 构建技术细节和历史版本见：[RELEASE_MANIFEST.md](E:\FelixFu\document\ZJU\2026AW\浙客松\RELEASE_MANIFEST.md)

便携版推荐用于演示；完整解压后运行 `DeskCare-M18/DeskCare-M18.exe --demo-scenario`。单文件版需等待首次自解压。发布包尚未代码签名。

## 关键文件

- 新增 [demo_scenario.py](E:\FelixFu\document\ZJU\2026AW\浙客松\deskcare\demo_scenario.py)：可重复、离线、仅写入隔离演示库的场景编排。
- 更新 [app.py](E:\FelixFu\document\ZJU\2026AW\浙客松\deskcare\app.py)、[main_window.py](E:\FelixFu\document\ZJU\2026AW\浙客松\deskcare\ui\main_window.py)、[report_engine.py](E:\FelixFu\document\ZJU\2026AW\浙客松\deskcare\services\report_engine.py) 和 [database.py](E:\FelixFu\document\ZJU\2026AW\浙客松\deskcare\storage\database.py)。
- 新增 [test_demo_scenario.py](E:\FelixFu\document\ZJU\2026AW\浙客松\tests\test_demo_scenario.py)；扩充普通中文/演示提示界面测试。
- 项目累计阶段进度继续维护在 [PROGRESS.md](E:\FelixFu\document\ZJU\2026AW\浙客松\PROGRESS.md)。

## 遗留问题与下一步

- 需要用户在目标 Windows 机器按 `docs/M5_演示脚本.md` 体验完整演示流程，并反馈讲解是否自然、是否遇到卡顿或看不懂的词。
- 托盘开关、真实麦克风权限/Vosk 中文识别、锁屏与唤醒、多显示器及 DPI 缩放、非开发者可用性，仍需人工验收。
- 该演示是确定性的产品流程样例，不是基于真实使用的 AI 个性化效果，也不是医学建议或效果证明。
- 当前没有声称“没有 bug”；自动化与包启动检查通过后，仍要结合目标设备和用户走查继续迭代。
