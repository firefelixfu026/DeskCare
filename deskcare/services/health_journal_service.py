"""Optional self-record → explicitly confirmed action → voluntary follow-up."""

from datetime import datetime, timedelta

from deskcare.domain.health_journal import CHANGE_LABELS, SEVERITY_LABELS
from deskcare.storage.health_journal import HealthJournalRepository


class HealthJournalService:
    def __init__(self, repository, task_service=None, *, now=None):
        self.repository = HealthJournalRepository(repository)
        self.task_service = task_service
        self.now = now or (lambda: datetime.now().astimezone())
        self._listeners = []

    @property
    def enabled(self):
        return self.repository.enabled

    def subscribe(self, listener):
        self._listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self):
        for listener in tuple(self._listeners):
            listener()

    def set_enabled(self, enabled):
        self.repository.set_enabled(enabled)
        self.notify()

    def clear(self):
        self.repository.clear()
        self.notify()

    def events(self, start=None, end=None):
        return self.repository.events(start, end)

    @staticmethod
    def _text(value, limit, required=False):
        if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
            raise ValueError(f"请填写有效内容（最多 {limit} 字）。")
        return value.strip()

    def _when(self, value):
        if not isinstance(value, datetime):
            raise ValueError("请填写有效日期和时间。")
        when = value.astimezone().replace(second=0, microsecond=0)
        if when > self.now().astimezone() + timedelta(minutes=1):
            raise ValueError("记录时间不能在未来。")
        return when

    def save(self, *, occurred_at, description, body_area="", severity=None, duration_minutes=None, notes="", event_id=None):
        if not self.enabled:
            raise PermissionError("请先单独开启不适记录。")
        when = self._when(occurred_at)
        if severity not in SEVERITY_LABELS:
            raise ValueError("请选择有效的自报程度。")
        if duration_minutes is not None and (type(duration_minutes) is not int or not 0 <= duration_minutes <= 10080):
            raise ValueError("持续分钟可留空，填写时应为 0–10080 的整数。")
        if event_id is not None:
            self.repository.event(event_id)
            if any(item.recorded_at < when for item in self.repository.followups(event_id)):
                raise ValueError("发生时间不能晚于已有补记；请先核对补记时间。")
        event = self.repository.save_event(event_id, (
            when.isoformat(timespec="minutes"), self._text(body_area, 80), self._text(description, 500, True),
            severity, duration_minutes, self._text(notes, 2000)))
        self.notify()
        return event

    def delete(self, event_id):
        self.repository.delete_event(event_id)
        self.notify()

    def followup(self, event_id, *, recorded_at, change, note=""):
        event = self.repository.event(event_id)
        when = self._when(recorded_at)
        if when < event.occurred_at:
            raise ValueError("补记时间不能早于发生时间。")
        if change not in CHANGE_LABELS:
            raise ValueError("请选择这次自报变化；不想记录可取消。")
        self.repository.add_followup(event_id, when, change, self._text(note, 2000))
        self.notify()

    def delete_followup(self, event_id, followup_id):
        self.repository.delete_followup(event_id, followup_id)
        self.notify()

    def add_action(self, event_id, draft, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError("行动安排需要你确认后才能加入任务。")
        task = self.repository.add_action(event_id, draft)
        if self.task_service is not None:
            self.task_service.notify_external_change()
        self.notify()
        return task

    def review(self, event_id):
        event = self.repository.event(event_id)
        followups = self.repository.followups(event_id)
        actions = self.repository.actions(event_id)
        lines = ["我的不适记录（本人填写，不是医学结论）", "",
                 f"发生时间：{event.occurred_at:%Y-%m-%d %H:%M}",
                 f"部位：{event.body_area or '未填写'}", f"描述：{event.description}",
                 f"自报程度：{SEVERITY_LABELS[event.severity]}",
                 f"持续分钟：{event.duration_minutes if event.duration_minutes is not None else '未填写'}",
                 f"备注：{event.notes or '未填写'}", "", "我确认的行动安排"]
        statuses = {"todo": "待处理", "doing": "进行中", "done": "标记完成"}
        lines.extend([f"• {item.title} · {statuses.get(item.status, '未知')}" if item.task_id else "• 关联任务已删除"
                      for item in actions] or ["未加入任务"])
        lines.extend(["", "后续补记（本人填写）"])
        lines.extend([f"• {item.recorded_at:%Y-%m-%d %H:%M} · {CHANGE_LABELS[item.change]}" +
                      (f"\n  {item.note}" if item.note else "") for item in followups] or ["尚未补记，不推断已经好转或恢复。"])
        lines.extend(["", "任务完成不等于不适改善；记录不说明病因。本页未调用任何 AI。"])
        return "\n".join(lines)
