# DeskCare M6｜Windows 发布清单

生成日期：2026-10-14（Asia/Shanghai）

## 推荐交付物

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-2.0.0-M6-windows-x64-portable.zip` | 推荐的 onedir 便携包，完整解压后运行 `DeskCare/DeskCare.exe` | 49,709,681 bytes | `C1B47885D298580A51BF3CB616FC45BBCEF829C598C5D07D7483C8385D9BAED1` |
| `release/DeskCare-2.0.0-M6-windows-x64-onefile.zip` | 单文件备选包，首次启动较慢 | 47,853,972 bytes | `381BB590361772A1CA802523DF4571EF41C9105EFBFAAB783BD4A3E1E11D0353` |
| `release/DeskCare-2.0.0-M6-source.zip` | 可审阅源码、测试、脚本、公开资源、示例和文档 | 960,198 bytes | `454A69982448F014AF7F6FDA271A4E3CF7DF60296D5B1D7E39AF1837FD8E54D5` |

`release/SHA256SUMS.txt` 保存相同校验值。正式演示优先使用 portable 包，避免 onefile 首次释放 Qt 运行文件带来的等待。

## 构建与验收证据

- Windows 11，Python 3.12.7，PySide6 6.12.0，PyInstaller 6.22.3。
- E 盘正式项目执行 `python -m pytest -q`：**65 passed**。
- `python -m compileall -q deskcare tests scripts`：通过。
- `python -m pip check`：`No broken requirements found.`
- onedir 和 onefile 原始产物均通过 `scripts/verify_windows_package.ps1`。
- 两个 ZIP 都重新解压到独立临时目录，并从解压内容再次通过同一启动验收：出现 `DeskCare` 主窗口，没有 `Unhandled exception`。
- 源代码 ZIP 使用明确白名单生成，共 94 个条目；检查确认不含 `.venv`、`build`、`dist`、`release`、`__pycache__`、pytest 临时目录、SQLite 数据库或自引用的发布清单。
- 验收临时目录均已删除；发布目录不包含测试数据库或用户数据。

## 运行与隐私边界

- 首次启动的活动监测、BodyLog、本地 AI、提醒反馈个性化均默认关闭。
- 不读取窗口标题、网页 URL、键盘内容、截图、剪贴板或未选择文件。
- 用户数据默认位于 `%LOCALAPPDATA%\DeskCare\deskcare.sqlite3`，不随发布 ZIP 分发。
- 本地 AI 只允许回环地址，模型输出仍须预览、校验和用户确认；发布包不包含模型，也不会自动下载模型。
- 应用内清除使用 SQLite `secure_delete` 并尝试 `VACUUM`，但不声称能清除系统备份或磁盘快照。

## 尚未完成的发布条件

- 当前机器没有已验证的本地模型，不能向评委宣称真实模型质量已经验收。
- 尚未完成 Windows 10、100%/150%/200% DPI、锁屏/睡眠和多小时运行的完整人工矩阵。
- 当前二进制未做代码签名，Windows SmartScreen 可能显示未知发布者。
- 项目目录当前没有 Git 仓库元数据；发布清单以文件哈希和测试记录为版本证据。

