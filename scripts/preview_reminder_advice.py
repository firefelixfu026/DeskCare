"""UI11 fictional previews: no user DB, credentials, OS sampling or model calls."""
import argparse
from datetime import datetime, timedelta
import os
import gc
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

from deskcare.ai.optional_local_llm import LocalAIService
from deskcare.config import ConfigStore
from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction, PolicyDecision
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.personalization_service import ReminderPersonalizationService
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=1040)
    parser.add_argument("--height", type=int, default=680)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    with TemporaryDirectory(prefix="fictional-ui11-", dir=args.output.resolve()) as temp:
        repo = UsageRepository(Path(temp) / "fake.sqlite3")
        ctl = MonitoringController(FakeActivityProvider(), initially_enabled=True)
        collector = ActivityCollector(ctl, repo)
        now = datetime.now().astimezone()
        collector._previous = ActivitySample(100, now, 0, "CODE", ActivityKind.ACTIVE, True, True)
        collector.continuous_active_seconds = 42 * 60
        tasks = TaskService(repo)
        tasks.add_manual("虚构示例：收尾展示材料", due_at=now+timedelta(minutes=8), estimated_minutes=30)
        personal = ReminderPersonalizationService(repo, initially_enabled=True)
        reminder = ReminderCoordinator(ctl, collector, tasks, repo, personalization_service=personal)
        local = LocalAIService(repo, initially_enabled=True)
        window = MainWindow(ConfigStore(), ctl, collector, tasks, reminder, repo,
                            local_ai_service=local, personalization_service=personal)
        window.resize(args.width, args.height)
        window.show()
        # Explicit fictional fixtures, never feedback from a real user.
        for i in range(10):
            event = repo.add_reminder_event(occurred_at=now-timedelta(minutes=15-i),
                decision=PolicyDecision(BreakAction.SOFT_NOTIFY, ("FIXTURE",), "虚构演示", 60),
                mode="normal", active_minutes=40)
            repo.update_reminder_response(event.id, "BAD_TIMING" if i < 8 else "SKIP", now)
        personal.refresh()
        app.processEvents()
        window.grab().save(str(args.output / "advice-today-banner.png"))
        window.navigation.setCurrentRow(4)
        window.settings_page.sections.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(args.output / "advice-settings.png"))
        window._open_reminder_advice()
        dialog = window._reminder_advice_dialog
        app.processEvents()
        dialog.grab().save(str(args.output / "advice-local-rule.png"))
        dialog.task.setCurrentIndex(1)
        dialog.service.set_enabled(True)  # fictional temp DB only
        dialog.consent.blockSignals(True)
        dialog.consent.setChecked(True)
        dialog.consent.blockSignals(False)
        dialog.prepare_request()  # serialization only; never send
        app.processEvents()
        dialog.grab().save(str(args.output / "advice-exact-preview.png"))
        dialog.advice = dialog.service.validate({"action": "review_interval", "evidence": ["task", "feedback"],
            "interval_minutes": 60}, dialog.context, source="模拟 AI 策略（非真实模型推理）")
        dialog.result.setPlainText(dialog.advice.text())
        dialog.details.setCurrentIndex(0)
        dialog.apply_button.setEnabled(True)
        dialog.status.setText("模拟输出，只检查布局；本次未调用模型、未读取密钥。")
        app.processEvents()
        dialog.grab().save(str(args.output / "advice-simulated-result.png"))
        dialog.reject()
        window._allow_close = True
        window.close()
        window.deleteLater()
        app.processEvents()
        gc.collect()
    print("Rendered 5 fictional UI11 screenshots; zero network calls.")


if __name__ == "__main__":
    main()
