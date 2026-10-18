import io
import zipfile
from datetime import datetime

from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.importers.loader import parse_selected_file
from deskcare.importers.text_importer import parse_text_bytes


def _xlsx_bytes(*, formula: bool = False, shared: bool = False) -> bytes:
    workbook = io.BytesIO()
    def cell(reference, value):
        if formula and reference == "C2":
            return f'<c r="{reference}"><f>2+3</f></c>'
        if shared:
            return f'<c r="{reference}" t="s"><v>{value}</v></c>'
        return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'

    sheet_cells = (
        f'<row r="1">{cell("A1", "0" if shared else "title")}'
        f'{cell("B1", "1" if shared else "due_at")}'
        f'{cell("C1", "2" if shared else "estimated_minutes")}</row>'
        f'<row r="2">{cell("A2", "3" if shared else "复习项目")}'
        f'{cell("B2", "4" if shared else "2026-10-20T18:00")}'
        f'{"<c r=\"C2\"><f>2+3</f></c>" if formula else "<c r=\"C2\"><v>30</v></c>"}</row>'
    )
    with zipfile.ZipFile(workbook, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Tasks" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        if shared:
            archive.writestr(
                "xl/sharedStrings.xml",
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<si><t>title</t></si><si><t>due_at</t></si><si><t>estimated_minutes</t></si>"
                "<si><t>复习项目</t></si><si><t>2026-10-20T18:00</t></si></sst>",
            )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{sheet_cells}</sheetData></worksheet>",
        )
    return workbook.getvalue()


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


def test_xlsx_dispatch_reads_values_only_and_preserves_review_gate(tmp_path):
    from deskcare.importers.xlsx_importer import parse_xlsx_bytes

    result = parse_xlsx_bytes(_xlsx_bytes(), "today.xlsx")

    assert result.source_name == "today.xlsx"
    assert result.can_confirm
    assert result.drafts[0].title == "复习项目"
    assert result.drafts[0].estimated_minutes == 30
    assert result.drafts[0].due_at == datetime(2026, 10, 20, 18, 0)

    selected = tmp_path / "today.xlsx"
    selected.write_bytes(_xlsx_bytes())
    from_path = parse_selected_file(selected)
    assert from_path.can_confirm
    assert from_path.drafts == result.drafts

    shared_result = parse_xlsx_bytes(_xlsx_bytes(shared=True), "shared.xlsx")
    assert shared_result.can_confirm
    assert shared_result.drafts == result.drafts


def test_xlsx_formula_corruption_and_untrusted_xml_fail_closed():
    from deskcare.importers.xlsx_importer import parse_xlsx_bytes

    formula_result = parse_xlsx_bytes(_xlsx_bytes(formula=True))
    assert not formula_result.drafts
    assert "公式单元格" in formula_result.issues[0].message

    damaged = parse_xlsx_bytes(b"not a zip workbook")
    assert not damaged.drafts
    assert damaged.issues[0].code == "invalid_xlsx"

    hostile = io.BytesIO()
    with zipfile.ZipFile(hostile, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<!DOCTYPE workbook [<!ENTITY x "expanded">]><workbook/>',
        )
    hostile_result = parse_xlsx_bytes(hostile.getvalue())
    assert not hostile_result.drafts
    assert "XML 声明" in hostile_result.issues[0].message

    expanded = io.BytesIO()
    with zipfile.ZipFile(expanded, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("padding.bin", b"0" * 8_000_001)
    expanded_result = parse_xlsx_bytes(expanded.getvalue())
    assert not expanded_result.drafts
    assert "解压后过大" in expanded_result.issues[0].message
