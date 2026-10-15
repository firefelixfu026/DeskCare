# M5 Windows 人工验收清单

## 源码启动与单实例

- [ ] 在项目根目录执行 `& .\.venv\Scripts\python.exe -m deskcare --demo`，窗口正常打开。
- [ ] 再执行一次同样命令，不出现第二个 DeskCare 主窗口，不产生第二套采样会话。
- [ ] 关闭窗口后，系统托盘可用时能从托盘恢复；托盘退出后进程结束。
- [ ] 系统托盘不可用时，关闭可见窗口仍能退出，不留下后台进程。

## 数据清除

- [ ] 先准备虚构任务、活动聚合、提醒反馈和 BodyLog，点击全部清除并选择“否”，数据仍在。
- [ ] 再确认清除，所有上述记录消失，活动和 BodyLog 授权都回到关闭。
- [ ] 清除不会删除程序文件；重新启动仍能创建干净数据库。
- [ ] 确认界面说明会压缩本地数据库，同时不把它描述为法证级永久擦除；如启用系统备份或磁盘快照，按 README 说明处理。

## PyInstaller onedir

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

- [ ] `dist\DeskCare\DeskCare.exe` 可以脱离 IDE 启动。
- [ ] 图标、四页 UI、托盘、SQLite 本地数据和报告导出可用。
- [ ] 无网络时仍可启动、导入任务、提醒、打卡和生成模板报告。
- [ ] 删除整个 `dist\DeskCare` 后无 DeskCare 后台服务继续运行。
- [ ] 若使用 `-OneFile`，`dist\DeskCare.exe` 可单独复制运行；不要把 onedir 的 exe 与其他构建的 `_internal` 混用。

## 稳定性与隐私

- [ ] 100%/150% DPI 下无明显裁切；锁屏/睡眠超过 60 秒不补算活动。
- [ ] 监测关闭/暂停后 provider 不再读取，退出后不再采样。
- [ ] 检查安装目录和日志中没有任务全文、BodyLog 内容、窗口标题、URL、键盘内容或截图。
- [ ] 执行 `python .\scripts\run_baseline.py`，保存虚构输出和运行环境，不将结果写成健康/效率优越性结论。
