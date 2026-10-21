"""Fictional UI14 archived/long-task previews, no model or personal database."""
import argparse
from datetime import date, datetime, time, timedelta
import gc
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.config import ConfigStore
from deskcare.domain.types import TaskStatus
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow
from deskcare.ui.task_dialog import TaskFormDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="ui14-fictional-", dir=args.output.resolve()) as temp:
        repo = UsageRepository(Path(temp) / "fictional.sqlite3")
        repo.set_setting("demo_mode", "true")
        tasks = TaskService(repo)
        today = date.today()
        for offset in range(3):
            for number in range(3):
                task = tasks.add_manual(f"虚构示例：第 {offset+1} 天完成的事项 {number+1}", planned_for=today-timedelta(days=4))
                tasks.set_status(task.id, TaskStatus.DONE)
                with repo._connect() as connection:
                    connection.execute("UPDATE tasks SET completed_at=? WHERE id=?",
                        (datetime.combine(today-timedelta(days=offset),time(17,30)).astimezone().isoformat(),task.id))
                connection.close()
        contest = tasks.add_manual("CTF 比赛（虚构示例）", planned_for=today-timedelta(days=1),
            starts_at=datetime.combine(today-timedelta(days=1),time.min), ends_at=datetime.combine(today+timedelta(days=3),time(23,59)))
        tasks.add_manual("整理当天的解题记录（虚构示例）", planned_for=today, estimated_minutes=30)
        window = MainWindow(ConfigStore(), MonitoringController(FakeActivityProvider()), task_service=tasks, repository=repo)
        window.resize(1240,820)
        window.show()
        app.processEvents()
        window.grab().save(str(args.output / "today-long-task.png"))
        window.today_page.task_scope.setCurrentIndex(2)
        app.processEvents()
        window.grab().save(str(args.output / "completed-all-dates.png"))
        widget = window.today_page.completed_date
        widget.setCurrentIndex(widget.findData((today-timedelta(days=1)).isoformat()))
        app.processEvents()
        window.grab().save(str(args.output / "completed-selected-date.png"))
        form = TaskFormDialog(window,contest)
        form.show()
        app.processEvents()
        form.grab().save(str(args.output / "long-task-form.png"))
        form.close()
        form.deleteLater()
        window._allow_close=True
        window.close()
        window.deleteLater()
        app.processEvents()
        gc.collect()
    print("Rendered 4 fictional UI14 task screens; no personal data or AI requests.")


if __name__ == "__main__":
    main()
