"""PyInstaller entry point; the source package keeps ``python -m deskcare``."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_DLL_DIRECTORY_HANDLES = []


def _register_frozen_qt_dll_directory() -> None:
    """Make the bundled PySide6 DLLs discoverable before importing QtCore.

    Windows does not always search PyInstaller's nested ``PySide6`` directory
    when a bundled extension imports ``Qt6Core.dll``.  Keeping the directory
    handle alive is required for the registration to remain active.
    """

    if not getattr(sys, "frozen", False) or not hasattr(os, "add_dll_directory"):
        return
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    directories = (
        bundle_root,
        bundle_root / "_internal",
        bundle_root / "PySide6",
        bundle_root / "shiboken6",
        bundle_root / "_internal" / "PySide6",
        bundle_root / "_internal" / "shiboken6",
    )
    existing_path = os.environ.get("PATH", "")
    path_prefix = [str(directory) for directory in directories if directory.is_dir()]
    if path_prefix:
        os.environ["PATH"] = os.pathsep.join(path_prefix + [existing_path])
    for directory in directories:
        if directory.is_dir():
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))


_register_frozen_qt_dll_directory()

from deskcare.app import main


if __name__ == "__main__":
    raise SystemExit(main())
