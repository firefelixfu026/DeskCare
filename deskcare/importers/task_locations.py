"""Source-grounded location suggestions; never geocode or infer an address."""
import re


LOCATION_PREFIX = "地点："


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
