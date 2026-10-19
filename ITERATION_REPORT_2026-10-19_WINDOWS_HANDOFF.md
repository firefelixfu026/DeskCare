# DeskCare 迭代报告：Windows 交付易用性复核

日期：2026-10-19（Asia/Shanghai）
项目：`E:\FelixFu\document\ZJU\2026AW\浙客松`

## 本轮处理

- 新增面向普通使用者的 [Windows 常见问题与故障排查](E:\FelixFu\document\ZJU\2026AW\浙客松\docs\Windows_常见问题与故障排查.md)，按真实功能说明覆盖便携包/DLL、授权与统计、可选语音、AI 连接、任务/报告保存、数据位置与清除、反馈时隐私注意事项。
- 对照实际 ZIP 清单发现便携版采用“ZIP 外层文件夹 → 内层 `DeskCare-M18` 程序目录”的结构；README 与 [M18 运行说明](E:\FelixFu\document\ZJU\2026AW\浙客松\docs\M18_运行说明.md)已明确便携版和单文件版的可执行文件位置、工作目录及演示启动参数。
- 两份 ZIP 都附带运行说明和故障排查文档。对 ZIP 目录清单做了敏感独立文件名检查：未发现 `.env`、SQLite 数据库或 Vosk/ONNX 模型文件。此检查只审文件名/归档内容列表，不构成二进制或源代码密钥扫描。
- 更新的 ZIP 已重算并与 SHA-256 清单核对一致。

## 当前交付包

- [便携版 ZIP](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-portable.zip)：78,284,045 bytes；SHA-256 `12831D16740870E8B16E21E9D84F417D718BA74F8C760C4B820FF8E32FA23B65`。
- [单文件 ZIP](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-windows-x64-onefile.zip)：75,532,347 bytes；SHA-256 `2673F1D49C2A0BAEAC5DCB669E106C99EE818B8C363005FB2BFBA655B36FA8D5`。
- 哈希记录：[DeskCare-M18-SHA256.txt](E:\FelixFu\document\ZJU\2026AW\浙客松\release\DeskCare-M18-SHA256.txt)。

## 验证边界

- SHA-256 与清单匹配；ZIP 目录列表包含两份说明文档和预期 exe 路径。当前会话对已解压发布包的完整启动验证记录见 [上一轮午夜边界报告](E:\FelixFu\document\ZJU\2026AW\浙客松\ITERATION_REPORT_2026-10-18_MIDNIGHT_FIX.md)。
- 自动化仍为 113 项、112 通过、1 跳过；跳过项是沙箱限制的本机 socket 探测。故障指南内容是基于代码/文档的操作指引，不表示其每种故障都已在不同用户设备实测。
- 本轮未宣称完成真实 Windows 托盘、麦克风/Vosk、DPI/多屏、SmartScreen、干净电脑或普通用户理解度验收；这些仍需目标设备和非开发者参与。

## 下一步

先由用户在目标机按运行说明启动推荐便携版并体验 `--demo-scenario`，然后记录普通模式授权、任务编辑/导入、休息反馈、状态打卡、报告和退出/重启的实际表现。收到结果后优先修复真实阻塞问题；不以当前自动化通过替代人工验收。

## 2026-10-19 补充：高 DPI 自动化回归

- 在 `QT_QPA_PLATFORM=offscreen` 下，分别设置 `QT_SCALE_FACTOR=1.25` 和 `1.5`，运行 `test_m6_personalization.py`、`test_m8_companion.py`、`test_m11_plain_language.py`：两组均 **18 passed**。
- 这轮验证了既有 UI 断言在两个 Qt 缩放因子下仍通过；离屏环境不具备真实屏幕/DPI/多屏呈现，因此不能据此宣称实机 DPI 验收完成。
- 下一步仍是目标机实测便携包，包括真实 DPI/多屏、系统托盘、普通授权/暂停/退出，以及桌宠贴边可见性。

## 2026-10-19 补充：Qt 测试退出异常与包启动复核

- 全量回归时发现 M2 UI 测试断言虽通过，pytest 进程却可能在退出阶段返回 `0xC0000409`。单项测试没有复现；定位后为模块未持有 `QApplication` 包装对象导致的测试生命周期问题。
- 为 M2 UI 模块增加自动 fixture 持有 QApplication 至该模块结束，并在每个用例后关闭/删除其顶层窗口、处理 Qt 延迟删除事件。修改后该文件在默认、125%、150% Qt 缩放下均 **6 passed，退出码 0**；完整套件 **112 passed、1 skipped，退出码 0**。跳过项仍为沙箱不允许的本机 socket 探测。
- 按项目常用命令 `python -m pytest -q` 复测仍是 **112 passed、1 skipped，退出码 0**。源码入口 `python -m deskcare` 也在临时隔离 `LOCALAPPDATA` 下启动并创建隔离 SQLite 数据库，随后关闭进程及清理临时数据。
- 新运行便携 onedir 与 onefile 的 `--demo-scenario` 启动验证，均检测到标题为 DeskCare 的主窗口；校验脚本为每次运行设置临时 `LOCALAPPDATA` 并清理，未使用正式用户数据库。
- `pip check` 通过；两个 M18 ZIP 的 SHA-256 与发布清单匹配。应用二进制未改变；为让解压包内也附带最新版运行说明，已只替换两个 ZIP 中的说明文档条目并重算哈希。
- 复核参赛讲解流程后，运行说明增加“今日→使用统计→状态与报告”的页面顺序、两项任务/约 40 分钟模拟活动/一次提醒反馈/一条状态自报的预期，并明确 CSV 是自动解析和确认而非现场手工选文件；人工导入预览需另外按验收清单操作。
- 真实 Windows 托盘、实体麦克风/模型、DPI/多屏视觉与普通用户可理解性仍需实机/用户验收，不能由此轮启动冒烟测试替代。

## 2026-10-19 补充：语音运行依赖说明复核

- 静态检查 M18 便携 ZIP 发现 `vosk` Python 模块及 `libvosk.dll` 已随包提供；`scripts/build_windows.ps1` 也会在构建环境安装 Vosk 时将运行库收集进 onedir/onefile。语音模型并未随包提供。
- 修正 README、M8 语音验收、M18 运行说明和 Windows 故障指南：源码运行需要安装可选 `.[voice]`；M18 Windows 发布包无需用户另装 Python/Vosk，但仍需用户自行准备并选择模型。两个扩展目录与 ZIP 的运行说明/故障指南均已同步；EXE 未改变。这样避免普通用户把运行库和体积更大的识别模型混为一谈。
- 更新后的便携 ZIP 为 78,284,153 bytes，SHA-256 `9D51F5DF8AF2AFC4B8340FE037BB3E183D6A20DC553F5ED325194B561AB039BA`；onefile ZIP 为 75,532,455 bytes，SHA-256 `36B4A7A911E10AF7D83E008E644867155EA57A46C6BA6B3D3A8C02D073581E5F`。`RELEASE_MANIFEST.md` 与 `release/DeskCare-M18-SHA256.txt` 已同步更新。
- 对两个 ZIP 的全部归档成员进行读取校验；EXE 内容哈希与各自展开包中的 EXE 一致。该项是静态完整性复核，没有启动 GUI。
- 对源码/文档及两个 M18 ZIP 做凭据格式启发式扫描，没有发现 API token、AWS access key 或密钥赋值。便携包 Qt TLS DLL 仅匹配 PEM 私钥标记字符串，没有匹配到私钥内容；包内名称检查也未发现 `.env`、SQLite 用户库或 Vosk/ONNX 模型文件。此扫描不等同二进制反编译、完整秘密扫描或密码学审计。
- 更新后执行隔离全量回归：**112 passed、1 skipped，退出码 0**；`python -m compileall -q deskcare tests scripts`、`pip check`、`git diff --check` 通过。跳过项为当前沙箱不允许的 localhost socket 测试。
- 当前不操作桌面、不启应用窗口；真实麦克风、模型识别质量、托盘、多屏/DPI 与普通用户可理解性仍需按 Windows 实机清单验收。

## 2026-10-19 补充：语音 worker 生命周期与 M18 重建

- 新增无硬件依赖的模拟录音生命周期测试：模拟音频设备输入 PCM，实际启动 PySide6 转写线程；验证按下/松开、缓冲清理、后台转写、草稿确认门控和线程结束。`tests/test_m8_companion.py` **10 passed**。
- 修正语音线程未像其它后台 AI worker 一样保存 worker 强引用的问题：`CompanionWindow` 现在保留 `_voice_worker` 至线程完成，再释放引用并恢复按钮可用状态。
- 用 Windows 11、Python 3.12.7、PyInstaller 6.22.3 重建 onedir/onefile。全量 pytest **113 passed、1 skipped**；compileall、pip check、git diff --check 均通过。跳过项是当前沙箱不允许的 localhost socket 探测。
- 新 ZIP 已与各自 build EXE 做 SHA-256 一致性校验，并逐项读取归档内容。最新包没有启动 GUI；旧包启动记录不能外推到新 EXE。
- 最新便携 ZIP：78,286,446 bytes，SHA-256 `0B94689B066AE09EDC331F0962288520240C259B35EA2ACDDD628D49AA24AD25`；onefile ZIP：75,537,076 bytes，SHA-256 `441F8680E64AF76C32F6D8030469C329C44A2F2668DE10455041CC6CE905B202`；两个清单均已同步。
- 尝试同步现有解压版目录时，操作系统报告多个 DLL 被占用；为避免影响当前使用中的程序，没有关闭进程或继续覆盖。该解压目录可能部分混合，请不要从那里重启；最新 ZIP 保持独立、已验证，可在用户桌面空闲后解压至新目录。

## 2026-10-19 补充：麦克风中途异常回归

- 新增模拟麦克风报错测试：录制中途发生设备错误后，录音源停止并释放，计时器停止，音频缓冲清空，按钮恢复可用，且任务列表不变。
- 语音相关测试 **11 passed**；全量回归 **114 passed, 1 skipped**（33.03 秒，退出码 0）。唯一跳过是运行沙箱禁止 localhost socket 探测。
- 未调用真实麦克风，也没有启动或操控桌面 GUI；因此实际 Windows 权限撤销、设备断开、音频质量仍属未验收项。该测试仅改源测试文件，未改变应用二进制和发布包。

## 2026-10-19 补充：竞品定位与实机验收覆盖

- 根据 Workrave 官方资料，将竞品对照改为谨慎表述：其已提供活跃/空闲计时、微休息/较长休息/每日上限和日周月统计；DeskCare 不把这些单项能力称为独有。保留“任务、情境、提醒反馈与主动状态本地整合”为待验证定位假设，并明确未完成全面竞品审计。
- 产品说明补充后续路线：目标用户实测 → 简化首次使用 → 完善签名/安装和语音模型交付方案 → 验证模块整合价值。路线未被描述为当前完成能力。
- Windows 验收清单增加麦克风在录音途中撤权/断开设备的检查。只改文档；全量自动化结果仍为 **114 passed, 1 skipped**，没有重新打包。

## 2026-10-19 补充：报告未开启状态记录时的措辞

- 报告缺少自报数据时，原句“因此不提供身体状态总结”改成“你未开启状态打卡，因此本报告不包含个人状态记录”，避免让用户误以为应用会判断其身体状况。同步《决策引擎与AI规范》，增加准确文案断言。
- 报告专项 **5 passed**；全量 **114 passed, 1 skipped**（35.86 秒，退出码 0）。
- 当前 M18 EXE/ZIP 尚未包含这项源码文案改进；因用户表示正在使用电脑，本轮未重建或启动应用。发布包需在后续安全构建/实机验收后更新。

## 2026-10-19 补充：M18r1 打包与静态核验

- 在独立的新输出名 `DeskCare-M18r1` 下，使用 Windows 11、Python 3.12.7、PyInstaller 6.22.3 构建 onedir 和 onefile；没有覆盖旧 M18 产物，也没有启动 GUI。
- 便携 ZIP 78,269,366 bytes，SHA-256 `0DB83FBE6603EE2B3EF9FBC716B8107F0A5DCACDB0F01DD91CAB0BF3814D0B99`；onefile ZIP 75,536,102 bytes，SHA-256 `54E64D74785273757217E4C1717989AAFFC630149D96590EF52FACC50CA301D7`。校验值同步到 `release/DeskCare-M18r1-SHA256.txt` 和发布清单。
- 两个新 ZIP 的所有成员均成功读取，目录层级符合说明，包内 EXE SHA-256 与 dist 构建文件一致；静态检查未发现 SQLite 用户库、`.env` 或语音模型。README、运行说明和故障排查指南已切换到 M18r1。
- 只读解析 onedir/onefile 的 PyInstaller CArchive/PYZ，均确认新报告提示已经嵌入且旧提示已移除；这不是运行时启动验证。
- ZIP 文件名和文本说明的凭据格式启发式扫描未发现明显 API/AWS 凭据或私钥头；不包含 EXE 内部二进制扫描，因此不是完整安全审计。
- 新版尚未启动验收；静态归档校验不能证明 GUI 可启动。托盘、麦克风/模型、DPI/多屏、干净用户目录和普通用户走查仍未完成。旧 M18 ZIP 与已存在的旧解压目录未覆盖。

## 2026-10-19 补充：GitHub 同步边界

- 只读确认远程 `origin` 是 `https://github.com/firefelixfu026/DeskCare.git`；远端 `main` 当前查询结果为 `3b39283`，与本地基线提交一致。
- 当前源代码/测试/文档改动仍在本地工作树；release 目录因 `.gitignore` 被排除，不会进入源码提交。凭据格式启发式扫描未发现明显 API/AWS token。
- 提交准备时，Git 因 `.git/index.lock` 写入权限被拒而未能暂存任何文件；检查确认无暂存内容、无残留锁、未提交或推送。需在允许写 `.git` 的工作副本完成同步。
