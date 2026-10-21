## DeskCare UI15｜清单导入去重

下载 `DeskCare-UI15-Windows-x64.zip`，完整解压后运行 `DeskCare-UI15.exe`。也可用 `START-DEMO.cmd` 查看隔离演示数据；启动前从托盘退出旧版。本包未签名，请勿全局关闭安全防护。

- 导入时与全部现有任务比较，包括已完成任务，不受文件名影响。
- 明确重复项默认跳过；可能重复项先核对再勾选，原任务不被覆盖。
- 日期、时段和长期起止范围不同的同名任务分别保留。
- 本机及联网 AI 返回结果同样重新检查；已有任务库不额外上传给 AI。
- 保存时事务内再次检查，避免预览期间新增造成重复。保留 UI14 的完成日期归档及长期任务支持。

[使用说明与虚构演示截图](https://github.com/firefelixfu026/DeskCare/blob/main/docs/UI15_导入去重说明.md) · [历史版本归档](https://github.com/firefelixfu026/DeskCare/releases/tag/legacy-archive-2026-10-21)
