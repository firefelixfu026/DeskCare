"""Verify UI19 code matches its packaged runtime without reading personal data."""
from scripts.verify_ui15_bundle import main

if __name__ == '__main__':
    main('UI19', ('deskcare.ui.companion', 'deskcare.ui.task_status', 'deskcare.ui.choices'))
