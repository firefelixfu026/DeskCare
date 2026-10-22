"""Render fictional review and companion status selection, no model request."""
import argparse
import gc
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.ui.task_status import TaskStatusCombo
from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    with TemporaryDirectory(prefix='ui18-fictional-', dir=args.output.resolve()) as temp:
        repo = UsageRepository(Path(temp) / 'fictional.sqlite3')
        repo.set_setting('demo_mode', 'true')
        tasks = TaskService(repo)
        task = tasks.add_manual('整理小组讨论记录（虚构示例）', estimated_minutes=30)
        tasks.add_manual('完成实验报告（虚构示例）', estimated_minutes=90)
        reports = LocalReportService(repo)
        window = MainWindow(ConfigStore(), MonitoringController(FakeActivityProvider()), task_service=tasks,
                            repository=repo, report_service=reports)
        window.show()
        window.navigation.setCurrentRow(3)
        app.processEvents()
        window.grab().save(str(args.output / 'report-entry.png'))
        window._open_report_review()
        dialog = window._report_review_dialog
        # Explicitly synthetic aggregates, not model output or real observations.
        data, _ = reports.render(ReportPeriod('daily', date.today(), date.today()))
        data['usage'].update(active_minutes_estimate=128, idle_minutes_estimate=34)
        data['data_quality'].update(covered_minutes_estimate=162, days_with_activity=1)
        data['reminders'].update(shown=6, snoozed=3, skipped=1, bad_timing=1, break_intent_confirmed=1)
        dialog.begin(data)
        app.processEvents()
        dialog.grab().save(str(args.output / 'review-cards.png'))
        # Human-readable summary only; no prepare/send/key access in this renderer.
        dialog.preview.setPlainText(dialog.snapshot.human_preview())
        app.processEvents()
        dialog.grab().save(str(args.output / 'readable-preview.png'))
        dialog.reject()
        window.companion.show()
        app.processEvents()
        window.companion.grab().save(str(args.output / 'companion-tasks.png'))

        combo = window.companion.task_list.itemAt(0).widget().findChild(TaskStatusCombo)
        combo.showPopup()
        app.processEvents()
        combo.menu.grab().save(str(args.output / 'task-status-menu.png'))
        combo.hidePopup()
        window._allow_close = True
        window.close()
        window.deleteLater()
        app.processEvents()
        gc.collect()
    print('Rendered 5 fictional screens, no AI requests or personal data.')


if __name__ == '__main__':
    main()
