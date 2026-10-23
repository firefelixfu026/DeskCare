"""Fictional offline room extraction and simulated AI omissions; no requests."""
import argparse
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.ai.optional_local_llm import LocalLLMClient
from deskcare.importers.text_importer import parse_text_bytes
from deskcare.ui.task_dialog import ImportPreviewDialog
from deskcare.ui.theme import apply_theme


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    apply_theme(app)
    source = ('# 2031-10-23\n- CSSU全员大会（北4-205，15:00-17:00）\n'
              '- GOA全员大会（北2-112）（19:00-20:00）\n'
              '- 提交活动材料（北4-205）（ddl 24:00）（预计30分钟）\n'
              '- 复习题目 HW4-205（预计45分钟）\n')
    offline = parse_text_bytes(source.encode(), '虚构清单 · 本机教室识别.md')
    omitted = LocalLLMClient._to_import_result({'tasks': [
        {'title': 'CSSU全员大会', 'location': None, 'estimated_minutes': 30},
        {'title': 'GOA全员大会', 'location': None},
        {'title': '提交活动材料', 'location': '北4-205教室', 'source_row': 1},
        {'title': '复习题目 HW4-205', 'location': None},
    ]}, source, '虚构清单 · 模拟AI漏填或改写.md')
    for name, result in [('offline-room-notes.png', offline), ('ai-omission-fallback.png', omitted)]:
        dialog = ImportPreviewDialog(result)
        dialog.resize(1260, 560)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(args.output / name))
        dialog.reject()
        dialog.deleteLater()
        app.processEvents()
    print('Rendered two fictional import previews; no model, credentials or personal database.')


if __name__ == '__main__':
    main()
