"""Human-friendly Simplified Chinese labels used across DeskCare surfaces."""

APP_DISPLAY_NAMES = {
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "weixin": "微信",
    "wechat": "微信",
    "bilibili": "哔哩哔哩",
    "qq": "QQ",
    "teams": "Microsoft Teams",
    "winword": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpnt": "Microsoft PowerPoint",
    "wps": "WPS Office",
}

CATEGORY_DISPLAY_NAMES = {
    "CODE": "编程工具",
    "BROWSER": "浏览器",
    "MEETING": "会议与通讯",
    "OFFICE": "办公软件",
    "OTHER": "其他应用",
    "UNKNOWN": "暂无法识别",
}


def display_app_name(app_id: str) -> str:
    normalized = app_id.casefold().strip()
    return APP_DISPLAY_NAMES.get(normalized, normalized)
