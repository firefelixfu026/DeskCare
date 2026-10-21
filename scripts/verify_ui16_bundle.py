"""Verify the locally retained UI16 runtime matches current source."""
from scripts.verify_ui15_bundle import main

if __name__ == "__main__":
    main("UI16", ("deskcare.importers.task_locations",))
