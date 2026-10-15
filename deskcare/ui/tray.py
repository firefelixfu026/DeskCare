"""System tray integration with a visible-window fallback."""

from pathlib import Path

from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def build_tray_icon() -> QIcon:
    """Load the project icon, with a dependency-free fallback for packaging."""

    project_icon = Path(__file__).resolve().parents[2] / "assets" / "deskcare-app-icon.png"
    if project_icon.is_file():
        return QIcon(str(project_icon))

    pixmap = QPixmap(64, 64)
    pixmap.fill("transparent")
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush("#2F6B5F")
    painter.setPen("#2F6B5F")
    painter.drawEllipse(10, 10, 44, 44)
    painter.setBrush("#F4F0E8")
    painter.drawEllipse(22, 20, 20, 20)
    painter.end()
    return QIcon(pixmap)


class TrayController:
    """Own a tray icon and expose only user-facing actions."""

    def __init__(self, window, monitoring_controller) -> None:
        self.window = window
        self.monitoring_controller = monitoring_controller
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray: QSystemTrayIcon | None = None
        if not self.available:
            return

        self.tray = QSystemTrayIcon(build_tray_icon(), window)
        self.tray.setToolTip("DeskCare")
        menu = QMenu()
        show_action = QAction("打开 DeskCare", menu)
        show_action.triggered.connect(self.show_window)
        self.companion_action = QAction("显示桌面伙伴", menu)
        self.companion_action.setCheckable(True)
        self.companion_action.setChecked(self.window.companion.isVisible())
        self.companion_action.triggered.connect(self._toggle_companion)
        self.window.settings_page.companion_visibility_changed.connect(
            self.companion_action.setChecked
        )
        self.pause_action = QAction("暂停电脑使用统计", menu)
        self.pause_action.triggered.connect(self.toggle_pause)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show_action)
        menu.addAction(self.companion_action)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activated)
        self.monitoring_controller.subscribe(self._sync_pause_action)
        self.tray.show()

    def _sync_pause_action(self, enabled: bool, paused: bool) -> None:
        pause_action = getattr(self, "pause_action", None)
        if pause_action is not None:
            pause_action.setText("恢复电脑使用统计" if paused else "暂停电脑使用统计")
            pause_action.setEnabled(enabled)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def toggle_pause(self) -> None:
        self.monitoring_controller.toggle_paused()

    def _toggle_companion(self, visible: bool) -> None:
        self.window.settings_page.companion_enabled.setChecked(visible)

    def quit(self) -> None:
        self.window.request_quit()

    def hide(self) -> None:
        if self.tray is not None:
            self.tray.hide()

