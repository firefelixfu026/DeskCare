# M4 Windows 人工验收清单

在目标 Windows 设备执行，使用虚构演示数据；不要把真实健康记录、任务标题或报告截图提交到仓库。

## BodyLog 授权与删除

- [ ] 首次启动“个人状态打卡”默认关闭。
- [ ] 关闭 BodyLog 时不能保存状态记录，报告明确显示未授权。
- [ ] 开启 BodyLog 后可保存“无明显不适 / 有些不适 / 不想记录”。
- [ ] 同一天再次保存会更新当天记录，不产生重复行。
- [ ] “删除今天记录”后报告不再显示该记录。
- [ ] 设置页“清除全部 BodyLog 状态记录”会二次确认，只删除记录，不关闭授权。

## 报告与导出

- [ ] “今日日报/本周周报”均可刷新，页面显示时间范围和事实来源。
- [ ] 报告中的活动覆盖、活跃分钟、任务完成数和提醒反馈与页面/样例数据库一致。
- [ ] 未开启活动监测时报告不显示虚假 0 分钟。
- [ ] 周报有效活动日少于 3 天时不做趋势判断。
- [ ] 报告明确显示 BodyLog 是用户自报，不出现疲劳、视力、疾病或健康改善诊断。
- [ ] 点击“导出 Markdown”后由用户选择保存路径；打开导出文件可读且无敏感原始活动内容。

## 回归命令

```powershell
& .\.venv\Scripts\python.exe -m compileall -q deskcare tests
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pip check
```

预期：36 个测试通过，且 `pip check` 输出 `No broken requirements found.`
