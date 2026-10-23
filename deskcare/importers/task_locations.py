"""Source-grounded location suggestions; never geocode or infer an address."""
import re


LOCATION_PREFIX = "地点："

# Narrow campus-room notation, not arbitrary numeric identifiers or addresses.
_ROOM = re.compile(r"[东南西北中][0-9０-９]{1,2}[A-Za-zＡ-Ｚａ-ｚ]?\s*[-－–—]\s*"
                   r"[0-9０-９]{3,4}[A-Za-zＡ-Ｚａ-ｚ]?(?:教室|会议室)?")
_PLACE_LABEL = re.compile(r"(?:地点|地址|场地|教室)\s*[:：]\s*$|(?:位于|在|@)\s*$")
_NON_PLACE = re.compile(r"(?:编号|题号|工单|版本|型号|格式|代码)\s*[:：]?\s*[（(\[【]?\s*$")


def split_room_location(title):
    """Extract one explicit, bounded room literal; never interpret a room code.

    Keep original digits/dashes and don't turn 北4 into a guessed building name.
    Only task-adjacent parentheses, separators, whitespace or place labels count.
    Multiple room references, code labels and negation remain for manual review.
    """
    if not isinstance(title, str) or '\n' in title or '\r' in title:
        return title, ''
    rooms = list(_ROOM.finditer(title))
    if len(rooms) != 1:
        return title, ''
    match = rooms[0]
    before, after = title[:match.start()], title[match.end():]
    prefix = _PLACE_LABEL.search(before)
    if not prefix and (not before or before[-1] not in '（([【 \t,，;；'):
        return title, ''
    if after and after[0] not in '（）()[]【】 \t,，;；':
        return title, ''
    start = prefix.start() if prefix else match.start()
    context = title[:start].rstrip()
    if _NON_PLACE.search(context) or (prefix and re.search(r'(?:不|不是|不要|勿|非|原来|原先)$', context)):
        return title, ''
    cleaned = title[:start] + after
    cleaned = re.sub(r'[（(\[【]\s*[)）\]】]', '', cleaned)
    cleaned = re.sub(r'([（(\[【])\s*[,，;；]\s*', r'\1', cleaned)
    cleaned = re.sub(r'\s*[,，;；]\s*([)）\]】])', r'\1', cleaned)
    # Keep nonempty timing parentheses for split_task_time, especially a
    # single clock such as (10:00). Only empty/orphan delimiters are removable.
    cleaned = cleaned.strip(' ,，;；-').rstrip('（([【 ').lstrip('）)]】 ')
    if not cleaned or not re.search(r'\w', cleaned):
        return title, ''  # A task named only for the room must not disappear.
    return cleaned, match[0]


def checked_location(value, source_row, source_text):
    """Return a literal, single-line location and its source row, or nothing.

    Models may omit line numbers when the literal occurs on exactly one line.
    A provided but incorrect line number is not silently corrected.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 160 or any(ord(ch) < 32 for ch in value):
        return None
    value = value.strip()
    if not value:
        return None
    lines = source_text.splitlines()
    if source_row is not None:
        if isinstance(source_row, bool) or not isinstance(source_row, int) or not 1 <= source_row <= len(lines):
            return None
        matches = [source_row] if value in lines[source_row - 1] else []
    else:
        matches = [row for row, line in enumerate(lines, 1) if value in line]
    return (value, matches[0]) if len(matches) == 1 else None


def location_from_notes(notes):
    return next((line[len(LOCATION_PREFIX):].strip() for line in notes.splitlines()
                 if line.startswith(LOCATION_PREFIX)), "")


def title_without_location(title, location):
    if not location or location not in title:
        return title
    value = re.sub(r"(?:地点\s*[:：]|地址\s*[:：]|场地\s*[:：]|位于|在|@)\s*" + re.escape(location), "", title, count=1)
    if value == title:
        value = title.replace(location, "", 1)
    value = re.sub(r"[（(\[]\s*[)）\]]", "", value)
    return value.strip(" ,，;；:：-–—@()（）[]")


def merge_notes(original, addition):
    """Preserve personal notes and avoid repeated location lines.

    Over-limit drafts remain editable; UI/storage validation, not truncation,
    must prevent saving them. Never silently discard the extracted place.
    """
    result = original or ""
    for line in (addition or "").splitlines():
        if line.strip() and line.strip() not in {item.strip() for item in result.splitlines()}:
            candidate = result.rstrip() + ("\n" if result.strip() else "") + line
            result = candidate
    return result
