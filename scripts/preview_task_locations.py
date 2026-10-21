"""Render fictional location extraction; does not call a real model."""
import argparse
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from deskcare.ai.optional_local_llm import LocalLLMClient
from deskcare.ui.task_dialog import ImportPreviewDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    source = ("# 2031-10-23\n- 小组讨论（19:00-20:00）（地点：东1A-101）\n"
              "- 社团例会（20:00-21:00）（地点：活动中心201）\n- 整理阅读笔记\n")
    result = LocalLLMClient._to_import_result({"tasks": [
        {"title": "小组讨论", "location": "东1A-101", "source_row": 2},
        {"title": "社团例会", "location": "活动中心201", "source_row": 3},
        {"title": "整理阅读笔记", "estimated_minutes": 30, "location": None},
    ]}, source, "虚构清单（模拟AI结果）.md")
    dialog = ImportPreviewDialog(result)
    dialog.resize(1260, 580)
    dialog.table.item(0, 4).setText("记得带电脑\n" + result.drafts[0].notes)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(args.output / "location-notes.png"))
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
    print("Fictional source and simulated AI result rendered; no user data or model call.")


if __name__ == "__main__":
    main()
