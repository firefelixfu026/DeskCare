import os
import importlib.util
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the GUI smoke test",
)


def test_main_window_has_four_pages_and_monitoring_starts_off():
    code = (
        "from deskcare.app import create_application; "
        "app, window, tray = create_application([]); "
        "settings = window.pages.widget(3); settings.monitoring.setChecked(True); "
        "print(window.pages.count(), window.monitoring_controller.enabled, "
        "window.config_store.config.activity_monitoring_enabled); "
        "tray.hide(); window.close(); app.quit()"
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "4 True True"

