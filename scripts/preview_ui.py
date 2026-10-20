"""Render synthetic UI previews offscreen without a tray, OS provider or user DB."""

import argparse
import gc
import os
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

from deskcare.ai.optional_local_llm import LocalAIService
from deskcare.config import ConfigStore
from deskcare.demo_scenario import prepare_demo_scenario
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.report_engine import LocalReportService
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow
from deskcare.ui.task_dialog import TaskFormDialog
from deskcare.domain.types import TaskStatus, WellnessLevel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=1240)
    parser.add_argument("--height", type=int, default=820)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="deskcare-preview-", dir=args.output.resolve()) as temporary:
        repository = UsageRepository(Path(temporary) / "preview.sqlite3")
        prepare_demo_scenario(repository)
        for offset, level in ((0, WellnessLevel.COMFORTABLE), (2, WellnessLevel.COMFORTABLE)):
            repository.upsert_wellness_entry(date.today() - timedelta(days=offset), level)
        repository.set_consent("app_name_stats", True)
        for offset, minutes in enumerate((135, 95, 182, 150, 75, 120, 42)):
            repository.add_usage(date.today() - timedelta(days=offset), "CODE", active_seconds=minutes * 60)
        for category, seconds in (("BROWSER", 1800), ("OFFICE", 1200), ("MEETING", 900)):
            repository.add_usage(date.today(), category, active_seconds=seconds)
        for name, seconds in (("code", 5200), ("chrome", 3100), ("wechat", 2100), ("wps", 1500), ("dingTalk", 600)):
            repository.add_app_usage(date.today(), name.lower(), seconds)
        controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
        collector = ActivityCollector(controller, repository)
        tasks = TaskService(repository)
        preview_task = tasks.add_manual("整理下一次展示的材料和演示流程", estimated_minutes=30)
        tasks.set_status(preview_task.id, TaskStatus.DOING)
        reminder = ReminderCoordinator(controller, collector, tasks, repository)
        window = MainWindow(ConfigStore(), controller, collector, tasks, reminder, repository,
                            BodyLogService(repository, True), LocalReportService(repository),
                            LocalAIService(repository))
        window.resize(args.width, args.height)
        window.show()
        for name, nav, section in (("today", 0, None), ("usage", 1, 0), ("apps", 1, 1),
                                   ("status", 2, None), ("report", 3, None),
                                   ("settings", 4, 0), ("settings-reminders", 4, 1), ("settings-privacy", 4, 3)):
            window.navigation.setCurrentRow(nav)
            if nav == 1:
                window.usage_page.sections.setCurrentIndex(section)
            if nav == 4:
                window.settings_page.sections.setCurrentIndex(section)
            for chart in (window.usage_page.week_chart, window.usage_page.category_chart, window.usage_page.app_chart):
                chart.animation.stop()
                chart._animate(1.0)
            app.processEvents()
            if not window.grab().save(str(args.output / f"{name}.png")):
                raise RuntimeError("Could not write preview")
        window._preview_reminder()
        app.processEvents()
        window.reminder_popup.grab().save(str(args.output / "reminder-preview.png"))
        window.reminder_popup.hide()
        window.navigation.setCurrentRow(0)
        status_control = window.today_page.task_table.cellWidget(0, 0)
        status_control.showPopup()
        app.processEvents()
        status_control.menu.grab().save(str(args.output / "task-status-menu.png"))
        status_control.grab().save(str(args.output / "task-status-badge.png"))
        status_control.hidePopup()
        task_dialog = TaskFormDialog(window)
        task_dialog.show()
        app.processEvents()
        task_dialog.grab().save(str(args.output / "task-dialog.png"))
        task_dialog.close()
        window.companion.show()
        app.processEvents()
        window.companion.grab().save(str(args.output / "companion.png"))
        companion = window.companion
        companion.set_presentation("mascot", persist=False)
        for name, level in (("comfortable", WellnessLevel.COMFORTABLE),
                            ("uncomfortable", WellnessLevel.SOME_DISCOMFORT),
                            ("skip", WellnessLevel.PREFER_NOT_TO_SAY)):
            window.bodylog_service.save_today(level)
            app.processEvents()
            companion.grab().save(str(args.output / f"mascot-{name}.png"))
        companion.mascot.set_variant("drag")
        app.processEvents()
        companion.grab().save(str(args.output / "mascot-drag.png"))
        for side in ("left", "right"):
            companion._dock_to_edge(side, app.primaryScreen().availableGeometry())
            app.processEvents()
            companion.grab().save(str(args.output / f"mascot-peek-{side}.png"))
            companion._expand_from_edge()
        companion._show_quick_panel()
        app.processEvents()
        companion.grab().save(str(args.output / "mascot-tasks.png"))
        window.companion.hide()
        window._allow_close = True
        window.close()
        gc.collect()
    print(f"Rendered twenty fictional-data previews to {args.output}")


if __name__ == "__main__":
    main()
