import time
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

from test_ui11_reminder_advice import setup, transport
from test_ui12_assistant_ui import shell, pump
from deskcare.domain.lab_reading import LabRow
from deskcare.importers.lab_source import LabSource
from deskcare.ui.lab_reading import LabReadingDialog


def page(shell, monkeypatch):
    app, window, s = shell
    window.lab_button.click()
    dialog = window._lab_dialog
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    dialog.local_consent.setChecked(True)
    app.processEvents()
    return app, window, s, dialog


def test_header_entry_independent_consent_and_close_clears_all(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    assert dialog.isVisible() and s.repo.get_consent("lab_reading")
    assert not s.repo.get_consent("lab_reading_ai")
    dialog.raw.setPlainText("WBC 10.2 10^9/L 3.5-9.5\n未支持项目 1 g/L 2-3")
    dialog.parse.click()
    assert dialog.table.rowCount() == 1 and "1 行" in dialog.status.text()
    dialog.read.click()
    assert "先对照原件" in dialog.status.text()
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.read.click()
    assert "高于报告范围" in dialog.reading.toPlainText()
    assert "MedlinePlus" in dialog.reading.toPlainText()
    dialog.reject()
    assert dialog.service.rows == () and not dialog.raw.toPlainText()
    assert dialog.table.rowCount() == 0 and not dialog.reading.toPlainText()
    assert s.repo.get_consent("lab_reading")


def test_editing_either_source_or_cells_requires_new_verification(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    dialog.add_row(LabRow("WBC", "6", "10^9/L", "3-9", True))
    dialog.show_reading()
    dialog.table.item(0, 2).setText("10")
    assert dialog.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert not dialog.reading.toPlainText()
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.raw.setPlainText("a different source")
    assert dialog.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    dialog.reject()


def test_ai_requires_own_consent_and_human_preview_without_json(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    dialog.add_row(LabRow("WBC", "10.2", "10^9/L", "3-9", True))
    calls = []
    dialog.service.request_fn = transport({"focus_codes": ["WBC"], "question_ids": ["repeat"]}, calls)
    dialog._ask()
    assert not calls and "单独授权" in dialog.status.text()
    dialog.ai_consent.setChecked(True)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    dialog._ask()
    assert not calls
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    dialog._ask()
    pump(app, dialog)
    assert len(calls) == 1 and "AI 选择先阅读" in dialog.reading.toPlainText()
    dialog.ai_consent.setChecked(False)
    assert not dialog.reading.toPlainText() and not dialog.service.ai_enabled
    dialog.reject()


def test_closing_during_source_extraction_drops_sensitive_result(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    started, release = Event(), Event()
    def delayed():
        started.set()
        assert release.wait(5)
        return LabSource("fictional hidden text", 0, 1)
    dialog._start(delayed, dialog._source_done)
    assert started.wait(2)
    dialog.reject()
    release.set()
    pump(app, dialog)
    assert not dialog.raw.toPlainText() and not dialog.service.rows


def test_queued_old_result_and_data_clear_cannot_restore_report(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    dialog.add_row(LabRow("WBC", "6", "10^9/L", "3-9", True))
    dialog.show_reading()
    dialog._work_generation, dialog._work_revision = dialog._generation, dialog.service.revision
    dialog._callback = dialog._ai_done
    dialog.table.item(0, 2).setText("7")
    dialog._work_complete("stale sensitive result", "")
    assert "stale" not in dialog.reading.toPlainText()
    s.repo.set_consent("lab_reading", False)
    s.repo.set_consent("lab_reading_ai", False)
    window._refresh_after_data_clear()
    assert not dialog.isVisible() and not dialog.local_consent.isChecked() and not dialog.service.rows


def test_lab_dialog_geometry_and_column_presence(shell, monkeypatch):
    app, window, s, dialog = page(shell, monkeypatch)
    dialog.resize(900, 640)
    dialog.add_row(LabRow("平均红细胞体积", "90", "fL", "82-100", True))
    dialog.tabs.setCurrentIndex(1)
    app.processEvents()
    assert dialog.table.viewport().height() >= 250
    assert dialog.read.geometry().bottom() < dialog.height()
    assert dialog.table.horizontalHeader().count() == 6
    assert all(dialog.table.columnWidth(i) >= 60 for i in range(6))
    dialog.reject()
