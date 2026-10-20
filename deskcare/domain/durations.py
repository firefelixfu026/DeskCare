"""Explicit Chinese reminder intervals, never task duration or clock times."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation


NUMBER = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百]+)"
DURATION = rf"(?:{NUMBER}\s*(?:个)?\s*(?:小时|钟头)(?:\s*半|\s*(?:零|又)?\s*{NUMBER}\s*分(?:钟)?)?|半\s*(?:个)?\s*(?:小时|钟头)|{NUMBER}\s*分(?:钟)?|[一二两三四]\s*刻钟)"


def _number(text):
    text = text.replace("两", "二").replace("〇", "零")
    try:
        return Decimal(text)
    except InvalidOperation:
        digits = {char: i for i, char in enumerate("零一二三四五六七八九")}
        result = current = 0
        for char in text:
            if char in digits:
                current = digits[char]
            elif char in {"十", "百"}:
                result += (current or 1) * {"十": 10, "百": 100}[char]
                current = 0
            else:
                return None
        return Decimal(result + current)


def duration_minutes(text):
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    if text in {"半小时", "半个小时", "半钟头", "半个钟头"}:
        return 30
    match = re.fullmatch(rf"({NUMBER})刻钟", text)
    if match:
        value = _number(match[1]) * 15
    else:
        match = re.fullmatch(rf"({NUMBER})(?:个)?(?:小时|钟头)(?:(半)|(?:零|又)?({NUMBER})分(?:钟)?)?", text)
        if match:
            value = _number(match[1]) * 60 + (30 if match[2] else _number(match[3]) if match[3] else 0)
        else:
            match = re.fullmatch(rf"({NUMBER})分(?:钟)?", text)
            if not match:
                return None
            value = _number(match[1])
    return int(value) if value == value.to_integral_value() else None


def explicit_reminder_minutes(message):
    """Return one explicitly linked interval; don't mine all numbers in prose."""
    text = unicodedata.normalize("NFKC", message)
    text = re.sub(r"(?:一个半|一個半)(?:小时|鐘頭|钟头)", "一个小时半", text)
    text = re.sub(r"两个半(?:小时|钟头)", "两个小时半", text)
    # Keep the deadline/task background out; a clock like 22点30 is not a duration.
    clauses = re.split(r"[，,。；;\n]", text)
    values = []
    for clause in clauses:
        if re.search(r"(?:不要|别|不用|不想|取消).{0,10}(?:改|设|调整|提醒)", clause):
            continue
        patterns = (
            rf"(?:休息提醒|提醒(?:间隔|时间|频率)?|间隔).{{0,6}}?(?:改(?:为|成|到)?|设(?:置)?(?:为|成)?|调(?:整)?(?:到|成|为)?)\s*({DURATION})",
            rf"(?:改|设|调)[^，。；\n]{{0,6}}?(?:休息提醒|提醒间隔|提醒时间|提醒|间隔)[^，。；\n\d一二两三四五六七八九十半]{{0,4}}({DURATION})",
            rf"每(?:隔)?\s*({DURATION})[^，。；\n]{{0,5}}提醒",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, clause):
                minutes = duration_minutes(match[1])
                if minutes is not None:
                    values.append(minutes)
    distinct = set(values)
    return next(iter(distinct)) if len(distinct) == 1 else None
