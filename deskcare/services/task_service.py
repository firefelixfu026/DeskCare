"""M2 confirmed-task service.

The service deliberately has no file-reading method. A caller must first use
an importer to create drafts and then call ``confirm_import`` after the user
has reviewed them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

from deskcare.domain.types import Task, TaskDraft, TaskStatus
from deskcare.storage.database import UsageRepository


class TaskService:
    def __init__(self, repository: UsageRepository) -> None:
        self.repository = repository
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def list_today(self, day: date | None = None) -> Sequence[Task]:
        return self.repository.tasks_for_day(day)

    def next_confirmed_deadline(self, day: date | None = None, now: datetime | None = None) -> datetime | None:
        reference = (now or datetime.now().astimezone()).astimezone()
        target_day = day or reference.date()
        candidates = [
            task.due_at.astimezone()
            for task in self.list_today(target_day)
            if task.status is not TaskStatus.DONE
            and task.due_at is not None
            and task.due_at.astimezone() >= reference
        ]
        return min(candidates) if candidates else None

    def confirm_import(self, drafts: Sequence[TaskDraft], source_name: str) -> list[Task]:
        tasks = self.repository.confirm_tasks(tuple(drafts), source_name)
        self._notify()
        return tasks

    def add_manual(
        self,
        title: str,
        due_at: datetime | None = None,
        estimated_minutes: int | None = None,
    ) -> Task:
        task = self.repository.add_task(title, due_at, estimated_minutes)
        self._notify()
        return task

    def update(
        self,
        task_id: int,
        *,
        title: str,
        due_at: datetime | None = None,
        estimated_minutes: int | None = None,
    ) -> Task:
        task = self.repository.update_task(
            task_id,
            title=title,
            due_at=due_at,
            estimated_minutes=estimated_minutes,
        )
        self._notify()
        return task

    def set_status(self, task_id: int, status: TaskStatus) -> Task:
        task = self.repository.set_task_status(task_id, status)
        self._notify()
        return task

    def delete(self, task_id: int) -> None:
        self.repository.delete_task(task_id)
        self._notify()

