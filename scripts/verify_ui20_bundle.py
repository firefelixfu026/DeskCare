"""Compare UI20 source and packaged modules without opening personal data."""
from scripts.verify_ui15_bundle import main

if __name__ == '__main__':
    main('UI20', ('deskcare.importers.task_locations', 'deskcare.importers.text_importer',
                 'deskcare.importers.csv_importer', 'deskcare.importers.xlsx_importer'))
