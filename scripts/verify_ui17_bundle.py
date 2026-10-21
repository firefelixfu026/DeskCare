"""Read-only UI17 package/source validation, without opening personal data."""
from scripts.verify_ui15_bundle import main

if __name__ == "__main__":
    main("UI17", ("deskcare.ui.choices", "deskcare.ui.task_status", "deskcare.ui.companion",
        "deskcare.ui.assistant", "deskcare.ui.health_journal", "deskcare.ui.lab_reading",
        "deskcare.ui.reminder_popup", "deskcare.services.personalization_service",
        "deskcare.services.reminder_advice", "deskcare.ui.reminder_advice",
        "deskcare.ai.reminder_advisor", "deskcare.importers.task_locations"))
