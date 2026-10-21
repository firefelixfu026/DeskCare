"""Render fictional UI17 selections and preview-only desktop reminder."""
import argparse
import gc
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow
from deskcare.ui.reminder_popup import ReminderPopup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="ui17-fictional-", dir=args.output.resolve()) as temp:
        repo = UsageRepository(Path(temp) / "fictional.sqlite3")
        tasks = TaskService(repo)
        tasks.add_manual("整理讨论记录（虚构示例）", estimated_minutes=30)
        tasks.add_manual("完成实验报告（虚构示例）", estimated_minutes=90)
        window = MainWindow(ConfigStore(), MonitoringController(FakeActivityProvider()), task_service=tasks, repository=repo)
        window.resize(1240, 820)
        window.show()
        app.processEvents()
        window.today_page.context_mode.setCurrentIndex(1)
        window.today_page.context_mode.animation.setCurrentTime(150)
        app.processEvents()
        window.grab().save(str(args.output / "segmented-context.png"))
        combo = window.today_page.task_scope
        combo.showPopup()
        app.processEvents()
        combo._popup.grab().save(str(args.output / "rounded-list.png"))
        combo.hidePopup()
        status = window.today_page.task_table.cellWidget(0, 0)
        status.showPopup()
        app.processEvents()
        status.menu.grab().save(str(args.output / "rounded-status.png"))
        status.hidePopup()
        popup = ReminderPopup()
        popup.present(preview=True)
        app.processEvents()
        popup.grab().save(str(args.output / "four-feedback-options.png"))
        popup.close()
        popup.deleteLater()
        window._allow_close = True
        window.close()
        window.deleteLater()
        app.processEvents()
        gc.collect()
    print("Rendered 4 fictional UI17 screens; preview feedback not recorded.")


if __name__ == "__main__":
    main()
