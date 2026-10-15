# DeskCare M8｜Windows 发布清单

生成日期：2026-10-15（Asia/Shanghai）

## M8 发布包

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M8-windows-x64-portable.zip` | 推荐的 onedir 便携包，解压后运行 `DeskCare/DeskCare.exe` | 78,117,824 bytes | `8D324267BF2F07C7F6DAEF763D85DF814BDE53AFE28F51847FC656C20B68B6F7` |
| `release/DeskCare-M8-windows-x64-onefile.zip` | 单文件备选包，首次自解压较慢 | 75,386,548 bytes | `600B1459F3A14C7F1FA0C582025FD92EF64C81FEB1C2850EE40FF011E66511B9` |
| `release/DeskCare-M8-source.zip` | 可审阅源码、测试、脚本、公开资源和文档 | 976,806 bytes | `39CF43A0F17CBD11793C707A3A2C079F1EB6BE93FCB0385B225B1B73932D7D2D` |

M8 源码提交为 `6817ba1`；M8 三个发布包的 SHA-256 记录在 `release/SHA256SUMS.txt`。源代码 ZIP 由提交 `6817ba1` 生成，不包含虚拟环境、构建缓存、用户数据或自引用发布清单。

## M8 构建与验收

- Windows 11，Python 3.12.7，PySide6 6.12.0，PyInstaller 6.22.3，Vosk 0.3.45 runtime。
- 完整回归：**78 passed**；compileall 和 pip check 通过。
- onedir、onefile 均重建并启动验收通过；两个 M8 ZIP 在新目录解压后分别再次启动验收通过。
- 发行包包含 Vosk runtime 但不包含语音模型。真实麦克风权限、中文识别质量、多屏/DPI 仍待人工验收。

## M7 发布包（历史）

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M7-windows-x64-portable.zip` | 推荐的 onedir 便携包，解压后运行 `DeskCare/DeskCare.exe` | 49,726,653 bytes | `3532BB57AE4236AF26CB5C8A96E2D5540344C87F8A4F942A7625B180A755B9DE` |
| `release/DeskCare-M7-windows-x64-onefile.zip` | 单文件备选包，首次启动较慢 | 47,862,547 bytes | `779B703DAA8DA81D725DBD3600D1B45E25A78734D1AF882A2C820489281433AC` |
| `release/DeskCare-M7-source.zip` | 可审阅源码、测试、脚本、公开资源、示例和文档 | 963,032 bytes | `C6A657C8DD85874DB23DED4125993AC1E7D8C54F39919F360B60EE14937538CB` |

SHA-256 也保存在 `release/SHA256SUMS.txt`。M7 源码已推送到 [DeskCare GitHub 仓库](https://github.com/firefelixfu026/DeskCare)，M7 源码提交为 `aed842a`。源代码 ZIP 有意不包含本发布清单，避免出现自引用校验值。

## 构建与验收

- Windows 11，Python 3.12.7，PySide6 6.12.0，PyInstaller 6.22.3。
- E 盘权威项目执行完整测试：**72 passed**。
- `python -m compileall -q deskcare tests scripts`：通过。
- M7 onedir、onefile 均重新构建，并由 `scripts/verify_windows_package.ps1` 启动验收通过。
- M7 portable/onefile ZIP 在独立解压目录通过启动验收。
- 自动化测试覆盖应用明细独立授权、跨日聚合、标识校验、撤回清除、活动数据清除、设置持久化和原有功能回归。

## 隐私与边界

- 活动监测和具体应用统计分别授权，首次均关闭；应用统计仅保存规范化 executable stem 与按日活跃时长，不保存进程路径、启动参数、窗口标题或文档名。
- 用户关闭应用明细授权时立即删除已有应用级记录；活动类别统计授权不会被改变。
- 不读取键入内容、截图、网页 URL、剪贴板或未选择文件。活动时间是本地估计，不代表工作质量或健康状态。
- 轻活动提示可关闭、可跳过，不提供医学判断或疗效保证。
- 默认无遥测、无账号；M7 不增加云端 AI、语音录音或后台麦克风监听。
- SQLite 清除操作尽力使用 `secure_delete` 和 `VACUUM`，不声称可清除系统备份或磁盘快照。

## 尚未完成人工验收

- 需要在用户日常 Windows 环境手动检查开启/撤回应用明细授权、近 7 天统计显示，以及提醒建议的可读性和关闭效果。
- Windows 10、100%/150%/200% DPI、锁屏/睡眠、多屏和多小时运行矩阵尚未全部完成。
- 当前二进制未签名，Windows SmartScreen 可能显示未知发布者。
- 当前机器没有已验证的本地模型；M6 本地 AI 接口不能描述为已完成真实模型质量验收。
