"""An isolated fictional fixture for UI19 screenshots or Windows UI testing."""
import argparse
import gc
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from deskcare.domain.types import TaskStatus
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.task_status import TaskStatusCombo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    with TemporaryDirectory(prefix='ui19-fictional-', dir=args.output.resolve()) as temp:
        repo = UsageRepository(Path(temp) / 'fictional.sqlite3')
        tasks = TaskService(repo)
        tasks.add_manual('虚构示例：整理讨论记录', estimated_minutes=30)
        tasks.add_manual('虚构示例：编写实验报告', estimated_minutes=90)
        host = QWidget() if args.interactive else None
        if host is not None:
            host.setWindowTitle('DeskCare UI19 虚构任务层级测试')
            host.resize(580, 420)
            layout = QVBoxLayout(host)
            layout.addWidget(QLabel('仅虚构任务，非个人实例。测试右侧伙伴状态；点伙伴“隐藏”退出。'))
            host.show()
        window = CompanionWindow(tasks, repository=repo, parent=host)
        window.setWindowTitle('DeskCare UI19 虚构任务伙伴')
        window.hide_requested.connect(app.quit)
        window.show()
        if args.interactive:
            window.move(host.frameGeometry().right() - window.width() - 20,
                        host.frameGeometry().top() + 65)
            tasks.subscribe(lambda: print([(task.title, task.status.value) for task in tasks.list_all()], flush=True))
            QTimer.singleShot(240000, app.quit)
            print('Fictional fixture ready; no personal database or network. Hide exits. Auto-exit in 4 minutes.', flush=True)
            app.exec()
        else:
            app.processEvents()
            window.grab().save(str(args.output / 'companion-status.png'))
            combo = window.task_list.itemAt(0).widget().findChild(TaskStatusCombo)
            combo.showPopup()
            app.processEvents()
            combo.menu.grab().save(str(args.output / 'three-state-menu.png'))
            combo.menu.actions()[1].trigger()
            app.processEvents()
            assert tasks.list_today()[0].status is TaskStatus.DOING
            window.grab().save(str(args.output / 'doing-state.png'))
        window._day_timer.stop()
        window.hide()
        window.deleteLater()
        if host is not None:
            host.close()
            host.deleteLater()
        app.processEvents()
        gc.collect()
    print('Fictional fixture closed; personal tasks unchanged.', flush=True)


if __name__ == '__main__':
    main()
