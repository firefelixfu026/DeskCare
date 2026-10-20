"""Fictional UI12 screenshots; never contacts a model or personal database."""
import argparse
import gc
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from deskcare.ai.optional_local_llm import LocalAIService
from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="fictional-ui12-", dir=args.output.resolve()) as temporary:
        repo = UsageRepository(Path(temporary) / "fictional.sqlite3")
        controller = MonitoringController(FakeActivityProvider())
        collector = ActivityCollector(controller, repo)
        tasks = TaskService(repo)
        coord = ReminderCoordinator(controller, collector, tasks, repo)
        local = LocalAIService(repo, initially_enabled=True)
        window = MainWindow(ConfigStore(), controller, collector, tasks, coord, repo, local_ai_service=local)
        window.resize(1040, 680)
        window.show()
        app.processEvents()
        window.grab().save(str(args.output / "assistant-entry.png"))
        window._open_assistant()
        dialog = window._assistant_dialog
        app.processEvents()
        dialog.grab().save(str(args.output / "assistant-welcome.png"))
        service = dialog.service
        dialog.input.setPlainText("把提醒改成45分钟")
        service.set_enabled(True)  # Explicit synthetic temp permission only.
        dialog.consent.blockSignals(True)
        dialog.consent.setChecked(True)
        dialog.consent.blockSignals(False)
        request = service.prepare(dialog.input.toPlainText(), "local")
        def capture_preview():
            modal = app.activeModalWidget()
            assert modal is not None
            modal.grab().save(str(args.output / "assistant-send-preview.png"))
            modal.reject()
        QTimer.singleShot(50, capture_preview)
        assert not dialog.confirm_send(request)  # Only preview, no network.
        plan = service.validate({"tool": "set_interval", "arguments": {"minutes": 45}}, request)
        service._pending_plan = plan  # Explicitly simulated model output, not real inference.
        dialog.append(request.message, "你（虚构示例）")
        dialog._received(plan, "")
        dialog.status.setText("虚构示例：模拟工具提议，未调用模型。")
        app.processEvents()
        dialog.grab().save(str(args.output / "assistant-confirm-action.png"))
        dialog.execute_pending()
        dialog.status.setText("虚构示例：仅修改临时库，未调用模型。")
        app.processEvents()
        dialog.grab().save(str(args.output / "assistant-tool-result.png"))
        dialog.reject()
        window.navigation.setCurrentRow(4)
        window.settings_page.sections.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(args.output / "assistant-setting-synced.png"))
        window._allow_close = True
        window.close()
        window.deleteLater()
        app.processEvents()
        gc.collect()
    print("Rendered 6 fictional UI12 previews, zero model requests or real credentials.")


if __name__ == "__main__":
    main()
