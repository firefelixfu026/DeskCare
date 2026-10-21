"""Render fictional import review, without real data or model calls."""
import argparse
from datetime import date, datetime, timedelta
import gc
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.domain.types import TaskDraft, TaskStatus
from deskcare.importers.base import ImportResult
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.task_dialog import ImportPreviewDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="ui15-fictional-", dir=args.output.resolve()) as temp:
        tasks = TaskService(UsageRepository(Path(temp) / "fictional.sqlite3"))
        day = date.today()
        tasks.add_manual("整理实验报告（虚构）", planned_for=day)
        done = tasks.add_manual("完成阅读笔记（虚构）", planned_for=day)
        tasks.set_status(done.id, TaskStatus.DONE)
        tasks.add_manual("准备小组讨论（虚构）", planned_for=day, due_at=datetime.combine(day, datetime.min.time()).replace(hour=18))
        result = ImportResult("虚构清单.md", (
            TaskDraft("整理实验报告（虚构）", planned_for=day),
            TaskDraft("完成阅读笔记（虚构）", planned_for=day),
            TaskDraft("准备小组讨论（虚构）", planned_for=day),
            TaskDraft("整理当天错题（虚构）", planned_for=day),
            TaskDraft("整理当天错题（虚构）", planned_for=day),
            TaskDraft("整理实验报告（虚构）", planned_for=day+timedelta(days=1)),
        ))
        dialog = ImportPreviewDialog(result, existing_tasks=tasks.list_all)
        dialog.resize(1260, 620)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(args.output / "import-review.png"))
        dialog.close()
        dialog.deleteLater()
        del dialog, tasks
        app.processEvents()
        gc.collect()
    print("Rendered fictional import review; no personal data or AI calls.")


if __name__ == "__main__":
    main()
