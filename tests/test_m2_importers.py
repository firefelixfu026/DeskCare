from datetime import datetime

from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.importers.loader import parse_selected_file
from deskcare.importers.text_importer import parse_text_bytes


def test_markdown_utf8_bom_creates_reviewable_drafts_without_marking_done():
    result = parse_text_bytes(
        "\ufeff# 今日清单\n- [ ] 16:00 参加讨论\n- [x] 阅读文章\n- 整理笔记 30 分钟\n".encode(),
        "today.md",
        reference_now=datetime(2026, 10, 14, 9, 0),
    )
    assert result.can_confirm
    assert [draft.title for draft in result.drafts] == ["参加讨论", "阅读文章", "整理笔记"]
    assert result.drafts[0].due_at == datetime(2026, 10, 14, 16, 0)
    assert "due_time_ambiguous" in result.drafts[0].uncertainty
    assert "source_marked_done_needs_confirmation" in result.drafts[1].uncertainty
    assert result.drafts[2].estimated_minutes == 30


def test_csv_bom_and_bad_rows_are_reported_without_silent_coercion():
    result = parse_csv_bytes(
        b"\xef\xbb\xbftitle,due_at,estimated_minutes\n"
        b"Good,2026-10-14T18:00,30\n"
        b"Bad,not-a-date,abc\n"
    )
    assert len(result.drafts) == 1
    assert {issue.code for issue in result.issues} == {"invalid_due_at", "invalid_estimated_minutes"}
    assert not result.can_confirm


def test_import_limits_empty_malformed_duplicate_and_unknown_column():
    assert parse_text_bytes(b"", "empty.txt").issues[0].code == "empty_file"
    duplicate = parse_text_bytes(b"- same\n- Same\n", "dup.txt")
    assert any(issue.code == "duplicate_title" for issue in duplicate.issues)
    unknown = parse_csv_bytes(b"name\nhello\n")
    assert unknown.issues[0].code == "missing_title_column"
    malformed = parse_csv_bytes(b"title,due_at\n\"unclosed,2026-01-01\n")
    assert malformed.issues[0].code == "malformed_csv"
    assert parse_text_bytes(b"x" * 1_000_001, "large.txt").issues[0].code == "file_too_large"


def test_selected_file_dispatch_rejects_unsupported_extension(tmp_path):
    source = tmp_path / "tasks.json"
    source.write_text("{}", encoding="utf-8")
    result = parse_selected_file(source)
    assert result.drafts == ()
    assert result.issues[0].code == "unsupported_type"
