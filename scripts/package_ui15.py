"""Package the reviewed UI15 runtime, not personal data or old builds."""
from scripts.package_ui14 import main

if __name__ == "__main__":
    main("UI15", "UI15_导入去重说明.md", "ui15")
