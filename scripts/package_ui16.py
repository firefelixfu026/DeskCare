"""Package UI16 without removing the locally runnable app."""
from scripts.package_ui14 import main

if __name__ == "__main__":
    main("UI16", "UI16_AI地点整理说明.md", "ui16")
