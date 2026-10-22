"""Verify UI18 packaged modules without launching personal data."""
from scripts.verify_ui15_bundle import main

if __name__ == '__main__':
    main('UI18', ('deskcare.services.report_review', 'deskcare.ui.report_review',
                 'deskcare.ui.companion', 'deskcare.ui.theme', 'deskcare.ai.structured_transport',
                 'deskcare.ai.reminder_advisor'))
