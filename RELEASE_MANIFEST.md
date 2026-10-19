# DeskCare Windows 发布清单

生成日期：2026-10-20（Asia/Shanghai）

## UI2 当前体验版本

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-UI2-windows-x64-portable.zip` | 完整解压后进入 `DeskCare-UI2`，运行 `DeskCare-UI2.exe` | 50,028,228 bytes | `4BF85D3521749396B4F25B00B62427AA155E3743C6F922C59E2887F3A80C9550` |

- Windows 11 / Python 3.12.7 / PyInstaller 6.22.3 onedir；应用版本 `2.0.0-ui2`。旧版和旧 onefile 不覆盖。
- 统一浅色弹窗及无原生黑框的 SVG 控件箭头；图表从当前帧和坐标轴连续插值；状态页近七天自主记录；精简桌面伙伴，移除内置语音、Vosk 和 QtMultimedia。
- 全量 **121 passed, 1 skipped**（39.85 秒，受限环境 localhost socket）；150% 离屏 UI 回归 **32 passed**；两种尺寸虚构数据预览检查；同名应用时长合并回归通过。
- ZIP 全部 **179** 条目 CRC 通过；EXE 与 dist、箭头 SVG 与源码一致；EXE 内七个修改的应用/UI 模块代码指纹与最终源码一致。无嵌入语音模块，ZIP 名称检查没有用户数据库、`.env` 或 ONNX 模型，不代表完整安全审计。
- 包内附 UI2 使用说明、迭代报告和故障指南。SHA 文件为 `release/DeskCare-UI2-SHA256.txt`。
- **未启动 UI2 EXE**，没有操作用户桌面或托盘。真实启动、多屏/DPI、系统主题及干净第二台 Windows 待验收。只读签名检查为 `NotSigned`，不提供签名安装器。

## UI1 此前界面体验版本

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-UI1-windows-x64-portable.zip` | 完整解压后进入 `DeskCare-UI1`，运行 `DeskCare-UI1.exe` | 78,283,576 bytes | `92C6772FC6226B1F974994D59681A32EA6107F320EEEAB27CF5EBACE6468B30F` |

- Windows / Python 3.12.7 / PyInstaller 6.22.3 onedir 构建完成；Qt 应用版本 `2.0.0-ui1`。本轮只交付新版便携包，旧 onefile 仍是旧界面。
- 五项左侧导航、四组设置；统一透明文字背景；活动柱状图、类别环形图与应用排行；Markdown 报告排版和本地数据变化通知刷新。
- 最终全量测试 **119 passed, 1 skipped**（30.06 秒，跳过为受限环境 localhost socket）；另有 Qt 150% 离屏 UI 回归及 1040×680、1240×820 虚构数据截图检查。
- ZIP 全部 262 条目 CRC 校验通过，包内 EXE 与 dist 构建 EXE 哈希一致；PyInstaller 静态归档中已确认新图表、主题、图标、报告预览模块及最终导航代码。文件名检查未发现独立用户数据库、`.env` 或 ONNX 模型；不等同完整二进制安全审计。
- 没有启动 EXE 或操作用户桌面；实际 Windows 启动、托盘、麦克风、真实多屏/DPI 仍待人工体验。

## M18r1 此前版本（报告措辞修正、语音错误回归）

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M18r1-windows-x64-portable.zip` | 推荐便携版；完整解压后运行 `DeskCare-M18r1/DeskCare-M18r1.exe` | 78,269,366 bytes | `0DB83FBE6603EE2B3EF9FBC716B8107F0A5DCACDB0F01DD91CAB0BF3814D0B99` |
| `release/DeskCare-M18r1-windows-x64-onefile.zip` | 单文件备选版 | 75,536,102 bytes | `54E64D74785273757217E4C1717989AAFFC630149D96590EF52FACC50CA301D7` |

### M18r1 构建与验收

- Windows 11，Python 3.12.7，PyInstaller 6.22.3；包含可选 Vosk runtime，不含语音模型。
- 构建前当前源码完整回归为 **114 passed, 1 skipped**；跳过项是沙箱禁止的本机 socket 探测。
- 新包将“未开启状态打卡”提示改为“你未开启状态打卡，因此本报告不包含个人状态记录”；录音中途设备错误也有模拟自动化回归。
- 两个 ZIP 的全部条目均已读取；包内 EXE SHA-256 与对应 dist 构建产物一致；未发现用户数据库或语音模型文件。
- 只读检查 PyInstaller CArchive/PYZ 内容，确认 onedir 和 onefile 都嵌入新报告提示，且未嵌入旧措辞；未启动 EXE。
- 对 ZIP 文件名及文本说明做凭据格式启发式扫描，未发现 `.env`、SQLite 用户库、Vosk/ONNX 模型、明显格式 API/AWS 凭据或私钥头。该检查不分析 EXE 内部二进制，不构成完整安全审计。
- **M18r1 EXE 尚未启动验收**；未启动 GUI、未访问麦克风。该校验只证明归档和构建文件一致，不证明 Windows 实际启动成功。目标机启动、托盘、麦克风、DPI/多屏及普通用户走查仍待验收。

## M18（此前版本，保留供追溯）

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M18-windows-x64-portable.zip` | 推荐便携版；完整解压后运行 `DeskCare-M18/DeskCare-M18.exe` | 78,286,446 bytes | `0B94689B066AE09EDC331F0962288520240C259B35EA2ACDDD628D49AA24AD25` |
| `release/DeskCare-M18-windows-x64-onefile.zip` | 单文件备选版 | 75,537,076 bytes | `441F8680E64AF76C32F6D8030469C329C44A2F2668DE10455041CC6CE905B202` |

## M18 构建与验收

- Windows 11，Python 3.12.7，PyInstaller 6.22.3；包含可选 Vosk runtime，不含模型文件。
- 这两个 ZIP 对应构建时的完整自动化回归：**113 passed, 1 skipped（114 项）**；`compileall`、`pip check` 通过。跳过项是沙箱禁止的本机 socket 探测。
- 2026-10-19 语音 worker 生命周期修复后，onedir 与 onefile 均用 Python 3.12.7 / PyInstaller 6.22.3 重建成功；新 ZIP 全量读取校验通过，包内 EXE 与新构建产物 SHA-256 一致。**这次最新 EXE 未启动验收**，旧构建启动记录不适用于新二进制。
- M18 增加模拟数据库隔离、提醒依据最小留痕、SQLite v7 兼容迁移、端到端一致性、导入表格空单元格保护、提醒卡字段回归和失败提示。
- 新增完整 `--demo-scenario` 虚构闭环；主窗口和报告都明确标注演示内容，空白演示库、场景演示库和正式用户库隔离；新构建 ZIP 与 SHA-256 已更新。
- 交付文档复核后修正了源码与发布包的 Vosk 依赖说明；语音生命周期重建后，运行说明明确提示最新包尚未启动验收，ZIP 与 SHA 清单已更新。
- 便携版原有展开目录在本轮同步新构建时遇到 DLL 文件占用，可能部分混合；没有关闭占用程序。不要从该旧展开目录重启；请将最新便携 ZIP 解压到新目录。此限制不影响已独立验证的两个 ZIP。
- 对源码/文档及 M18 包完成凭据格式启发式扫描，未发现 API token、AWS access key 或密钥赋值；Qt TLS 二进制中的 PEM 标记为格式支持字符串，未匹配到私钥内容。此检查不是完整二进制安全审计。
- 实际麦克风/模型、云端服务、普通用户走查、多屏/DPI、未签名 SmartScreen、干净第二台电脑均未验收；详情见 `docs/M15-M18_阶段验收与Windows实机清单.md`。
- 2026-10-19 构建后，当前源码增加麦克风错误回归并改进报告措辞；此前 M18 ZIP 未包含这些变更。后续已另行构建 M18r1，见本清单顶部；M18 旧 ZIP 保留不覆盖。

## M14 Final 此前版本（含圆形贴边伙伴与紧凑设置布局）

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M14-final-windows-x64-portable.zip` | 推荐的 onedir 便携包，解压后运行 `DeskCare.exe` | 78,248,533 bytes | `4A82D4BA57D56830409A91FAD70D8A5019D79A18190763580BBD9F097E1C3A61` |
| `release/DeskCare-M14-final-windows-x64-onefile.zip` | 单文件备选包，首次启动需自解压 | 75,522,360 bytes | `8B1929AF0E8A79440D2F492E1322CFB62F43B3AE53F1426365907CCB41346A33` |

## M14 构建与验收

- Windows 11，Python 3.12.7，PySide6 6.12.0，PyInstaller 6.22.3；包内包含 Vosk 0.3.45 运行库，不含语音模型。
- 完整自动化回归：**101 passed, 1 skipped**；`compileall`、`pip check` 通过。跳过项是当前沙箱禁用 socket 的本机模型检测测试。
- M14 onedir/onefile 均由 `scripts/build_windows.ps1 -Verify` / `-OneFile -Verify` 重新构建并启动验收；M14-final ZIP 在独立目录解压后也分别启动验收通过。
- 不提供签名安装器；未使用真实麦克风、Vosk 模型、云端 API Key 或真实服务商；这些依赖用户设备/选择，见 M8/M9/M13 人工验收文档。

## M13 Final 历史发布包

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M13-final-windows-x64-portable.zip` | M13 onedir 便携包 | 78,248,578 bytes | `CC0CC5A3848A1D2C0ED464396AE8EB60198EEF2E7E46D2B6904BF1A709303966` |
| `release/DeskCare-M13-final-windows-x64-onefile.zip` | M13 单文件备选包 | 75,520,143 bytes | `DE8FAA97B07FFF9DB65701862B049D37AA494C0C94DFA7028EE325B5730865F8` |

## M9 发布包

| 文件 | 用途 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `release/DeskCare-M9-windows-x64-portable.zip` | 推荐的 onedir 便携包，完整解压后运行 `DeskCare/DeskCare.exe` | 78,129,296 bytes | `8F1D3CF88E191F735B8A5E38EC2662717E4C9119479795079177F2CDFF60406A` |
| `release/DeskCare-M9-windows-x64-onefile.zip` | 单文件备选包，首次自解压较慢 | 75,400,392 bytes | `AD34AB025141D12A9952B627ABDC04A59842BE4EC48F635D6CFD43B56FA394B8` |
| `release/DeskCare-M9-source.zip` | Git 源码快照，含代码、测试、脚本与文档 | 985,866 bytes | `768F305E565B9B43D57A402A8B39AB501F690C5503849B6562F1268F53C85811` |

## M9 构建与验收

- Windows 11，Python 3.12.7，PySide6 6.12.0，PyInstaller 6.22.3，Vosk 0.3.45 runtime（不含语音模型）。
- 完整自动化回归：**88 passed**；`compileall`、`pip check` 通过。
- onedir 与 onefile 均经 `scripts/build_windows.ps1 -Verify` / `-OneFile -Verify` 启动验收；两个 ZIP 解压后也分别启动验收通过。
- 未使用真实 API Key、Windows Credential Manager 真实凭据或真实云端服务；请按 `docs/M9_云端任务AI隐私与验收.md` 自愿验收。

M9 源码 ZIP 对应提交 `f66b9f7`；三个 M9 包的 SHA-256 已追加在 `release/SHA256SUMS.txt`。

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
