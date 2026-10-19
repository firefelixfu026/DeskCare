"""Shared light surfaces and predictable controls, independent of OS theme."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

_ASSETS = (Path(__file__).resolve().parents[2] / "assets").as_posix()

STYLE = """
QWidget { color: #293F43; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QMessageBox, QInputDialog, QWidget#appShell { background: #F3F6F6; }
QLabel, QCheckBox, QStackedWidget, QScrollArea, QTabWidget::pane { background: transparent; }
QScrollArea > QWidget, QWidget#usageContent, QWidget#chartSurface { background: transparent; }
QLabel { border: none; }
QFrame#sidebar { background: #E8F0ED; border-right: 1px solid #DAE5E0; }
QLabel#brand { color: #235B50; font-size: 26px; font-weight: 700; }
QLabel#tagline, QLabel#sidebarFooter, QLabel#mutedText { color: #74858A; font-size: 12px; }
QListWidget#navigation, QListWidget#settingsNavigation { background: transparent; border: none; outline: none; }
QListWidget#navigation::item { color: #56716A; font-size: 14px; border-radius: 10px; padding: 8px 12px; margin: 3px 0; }
QListWidget#navigation::item:selected { color: #205D50; background: #D3E5DC; font-weight: 600; }
QListWidget#navigation::item:hover { background: #DEEAE4; }
QLabel#headerTitle { color: #234C47; font-size: 25px; font-weight: 700; }
QLabel#headerState, QLabel#statusBadge { padding: 7px 11px; border-radius: 13px; background: #E8EEEC; color: #6D8079; font-size: 12px; }
QLabel#headerState[tone="active"] { background: #DDEEE5; color: #286954; }
QLabel#headerState[tone="warning"] { background: #FFF0D8; color: #986C2D; }
QLabel#pageLead { color: #708287; font-size: 13px; padding-bottom: 4px; }
QFrame#card { background: #FFFFFF; border: 1px solid #E0E8E6; border-radius: 14px; }
QLabel#cardTitle { color: #2A504A; font-size: 16px; font-weight: 600; }
QLabel#cardBody, QLabel#contextLabel, QLabel#reminderBody { color: #687C7D; }
QLabel#metricValue { color: #295F53; font-size: 17px; padding-top: 8px; }
QLabel#wellnessSummary { color: #295F53; font-size: 25px; font-weight: 600; padding: 10px 0; }
QLabel#demoBanner { background: #FCF2DE; color: #936D32; border-radius: 8px; padding: 9px 12px; font-size: 12px; }
QFrame#reminderCard { background: #FFFAEF; border: 1px solid #EADDBD; border-radius: 14px; }
QLabel#reminderTitle { color: #8A692E; font-size: 16px; font-weight: 600; }
QLabel#reminderReason { color: #9A875F; font-size: 12px; }
QPushButton { background: #327D6B; color: white; border: 1px solid transparent; border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { background: #296956; }
QPushButton:pressed { background: #225B4C; }
QPushButton:disabled { background: #E4ECE8; color: #8B9B95; }
QPushButton#secondaryButton { background: #FFFFFF; color: #567169; border: 1px solid #CEDDD6; }
QPushButton#secondaryButton:hover { background: #EAF2EE; }
QPushButton#reminderAction { background: #D5AE69; color: #49391D; }
QCheckBox { spacing: 9px; padding: 9px 2px; }
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit { background: #FFFFFF; color: #294540; border: 1px solid #CEDDD6; border-radius: 7px; padding: 7px 9px; selection-background-color: #D3E6DC; }
QComboBox { padding-right: 30px; min-height: 20px; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 28px; border: none; background: transparent; }
QComboBox::down-arrow { image: url('__ASSETS__/chevron-down.svg'); width: 14px; height: 14px; }
QSpinBox { padding-right: 28px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 25px; border: none; background: transparent; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 25px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url('__ASSETS__/chevron-up.svg'); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url('__ASSETS__/chevron-down.svg'); width: 12px; height: 12px; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #77A899; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #294540; selection-background-color: #DDECE4; border: 1px solid #CEDDD6; }
QTableWidget { background: #FFFFFF; alternate-background-color: #F7FAF8; border: none; gridline-color: #EDF2EF; selection-background-color: #E1EEE7; selection-color: #234F43; }
QHeaderView::section { background: #F3F7F5; color: #6C8177; border: none; border-bottom: 1px solid #E3EBE6; padding: 10px 8px; }
QTableWidget#todayTasks { outline: none; }
QTableWidget#todayTasks::item { padding: 0 10px; border-bottom: 1px solid #F0F4F2; }
QTableWidget#todayTasks::item:selected { background: #EDF5F0; color: #294540; }
QTableWidget#todayTasks QHeaderView::section { background: #FFFFFF; color: #7C8D86; padding: 12px 10px; font-size: 12px; }
QComboBox#taskStatus { margin: 11px 10px; padding: 3px 8px; padding-right: 24px; min-height: 18px; border: 1px solid transparent; border-radius: 8px; background: #F0F3F2; color: #687D75; }
QComboBox#taskStatus[tone="doing"] { background: #FFF3DC; color: #906821; }
QComboBox#taskStatus[tone="done"] { background: #E5F2EB; color: #32735D; }
QComboBox#taskStatus:hover, QComboBox#taskStatus:focus { border-color: #9DBBAE; }
QComboBox#taskStatus::drop-down { width: 22px; }
QComboBox#taskStatus::down-arrow { width: 11px; height: 11px; }
QTextEdit, QTextBrowser { background: #FFFFFF; border: none; border-radius: 8px; padding: 10px; selection-background-color: #D5E8DE; }
QTabWidget::pane { border: none; padding-top: 14px; }
QTabBar::tab { background: transparent; color: #71857C; padding: 9px 17px; border-bottom: 2px solid transparent; margin-right: 8px; }
QTabBar::tab:selected { color: #2B6F5B; border-bottom: 2px solid #327D6B; font-weight: 600; }
QTabBar::tab:hover { background: #E8F0EC; }
QScrollArea#settingsScroll, QWidget#settingsContent { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #CBDAD2; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #234B40; color: white; border: none; padding: 7px; }
""".replace("__ASSETS__", _ASSETS)


def apply_theme(app):
    """Use a light palette for top-level dialogs as well as child widgets."""
    if app is None or app.property("deskcareTheme") == "ui2":
        return
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#F3F6F6"),
        (QPalette.ColorRole.WindowText, "#293F43"),
        (QPalette.ColorRole.Base, "#FFFFFF"),
        (QPalette.ColorRole.AlternateBase, "#F5F8F6"),
        (QPalette.ColorRole.Text, "#293F43"),
        (QPalette.ColorRole.Button, "#EAF1ED"),
        (QPalette.ColorRole.ButtonText, "#294540"),
        (QPalette.ColorRole.Highlight, "#D5E8DE"),
        (QPalette.ColorRole.HighlightedText, "#234F43"),
        (QPalette.ColorRole.ToolTipBase, "#234B40"),
        (QPalette.ColorRole.ToolTipText, "#FFFFFF"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    app.setProperty("deskcareTheme", "ui2")

REPORT_CSS = """
body { color: #324A48; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 14px; line-height: 1.7; }
h1 { color: #245A4B; font-size: 25px; margin-bottom: 20px; }
h2 { color: #336C5A; font-size: 17px; margin-top: 24px; margin-bottom: 10px; }
p, li { line-height: 1.7; margin-bottom: 10px; }
hr { color: #DDE8E2; }
"""
