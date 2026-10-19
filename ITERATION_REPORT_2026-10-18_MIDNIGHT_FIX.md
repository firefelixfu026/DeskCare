# DeskCare 迭代报告：演示场景午夜边界修复

日期：2026-10-18（Asia/Shanghai）
关联阶段：M15/M18 验收准备与完整演示场景

## 发现与修复

复核 `--demo-scenario` 时发现：若当天午夜后不到 40 分钟启动，虚构活动从前一日开始，日报只会统计被分到当天的部分，造成演示数字不完整。现在场景在该时间窗口将模拟提醒时刻安排在当天 00:40，从当天 00:00 生成完整 40 分钟活动；其他时间仍按当前本地时刻生成。此修复仅影响虚构演示时钟，不改正式采样或报告口径。

M15–M18 Windows 清单进一步加入 `--demo-scenario` 的任务/活动/提醒/状态/日报核对、同日幂等、报告标记和三种数据库隔离检查。没有要求用户更改系统时间。

## 验证

- `tests/test_demo_scenario.py` 午夜边界用例：通过；验证当天日报恰为 40 分钟、前一日没有演示活动。
- 全量 pytest：**113 项，112 passed、1 skipped**。跳过项是沙箱限制下的本机 socket 探测，不代表真实本机模型连接已验证。
- `pip check`、`compileall`、`git diff --check` 通过；Git 仅报告 LF/CRLF 行尾转换提示。
- 最新 onedir 与 onefile 构建检查通过；最新 portable 与 onefile ZIP 解压后都以 `--demo-scenario` 参数启动通过，使用隔离临时用户数据目录。

## 最新发布包

- [便携版](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-portable.zip)：78,280,140 bytes；SHA-256 `267FDB0BAB9B22CCB393EECED435BE9385FC0AABD7A4E758EA79DEC1D9ADD6C4`。
- [单文件版](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-onefile.zip)：75,528,444 bytes；SHA-256 `CF21C0ED7C447AF3A6E5ED923C0407AE4759093770BA8FE518B5AFF00B049CF1`。
- 哈希文件：[DeskCare-M18-SHA256.txt](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-SHA256.txt)。

## 仍需人工验收

以上证据覆盖自动化业务逻辑和打包启动，不覆盖用户逐页操作、真实 Windows 托盘、多显示器/DPI、麦克风/Vosk、干净电脑运行或普通用户是否看得懂。请按 [M15–M18 实机清单](E:\FelixFu\document\ZJU\2026AW\浙客松\docs\M15-M18_阶段验收与Windows实机清单.md) 继续验收；当前不宣称无 bug 或已完成真实用户验证。
