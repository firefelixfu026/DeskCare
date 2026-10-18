"""Bounded, read-only XLSX task-list importer using the Python standard library."""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree

from deskcare.importers.base import ImportIssue, ImportResult, MAX_FILE_BYTES
from deskcare.importers.csv_importer import parse_csv_bytes

MAX_ARCHIVE_MEMBERS = 128
MAX_UNCOMPRESSED_BYTES = 8_000_000
MAX_XML_BYTES = 4_000_000
MAX_COLUMNS = 32
_CELL_REF = re.compile(r"\$?([A-Z]{1,3})\$?[1-9][0-9]*\Z")
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class _XlsxError(ValueError):
    pass


def _safe_xml(archive: zipfile.ZipFile, member: str):
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise _XlsxError("工作簿缺少必要内容。") from exc
    if info.file_size > MAX_XML_BYTES:
        raise _XlsxError("工作表内容过大，未读取。")
    with archive.open(info) as source:
        data = source.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise _XlsxError("工作表内容过大，未读取。")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _XlsxError("工作簿包含不支持的 XML 声明。")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise _XlsxError("工作簿内容损坏，无法安全读取。") from exc


def _column_index(reference: str) -> int:
    match = _CELL_REF.fullmatch(reference)
    if match is None:
        raise _XlsxError("工作表包含无效单元格位置。")
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - ord("A") + 1
    if number > MAX_COLUMNS:
        raise _XlsxError("工作表列数过多；最多支持前 32 列。")
    return number - 1


def _worksheet_member(archive: zipfile.ZipFile) -> str:
    workbook = _safe_xml(archive, "xl/workbook.xml")
    sheets = workbook.findall(f"{{{_MAIN_NS}}}sheets/{{{_MAIN_NS}}}sheet")
    visible_sheets = [sheet for sheet in sheets if sheet.get("state", "visible") == "visible"]
    if not visible_sheets:
        raise _XlsxError("工作簿中没有可读取的可见工作表。")
    relation_id = visible_sheets[0].get(f"{{{_DOC_REL_NS}}}id")
    if not relation_id:
        raise _XlsxError("无法确定第一个工作表。")
    relationships = _safe_xml(archive, "xl/_rels/workbook.xml.rels")
    for relation in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship"):
        if relation.get("Id") != relation_id:
            continue
        if relation.get("TargetMode", "Internal").casefold() == "external":
            raise _XlsxError("不支持外部链接工作表。")
        target = relation.get("Target", "")
        member = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        )
        if not member.startswith("xl/") or member.startswith("../"):
            raise _XlsxError("工作表位置无效。")
        return member
    raise _XlsxError("工作簿引用的工作表不存在。")


def _cell_text(cell, shared_strings: list[str]) -> str:
    kind = cell.get("t", "n")
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        raise _XlsxError("不读取公式单元格；请将任务内容填写为普通文本或数字。")
    if kind == "inlineStr":
        inline = cell.find(f"{{{_MAIN_NS}}}is")
        return "" if inline is None else "".join(
            item.text or "" for item in inline.iter(f"{{{_MAIN_NS}}}t")
        )
    value = cell.find(f"{{{_MAIN_NS}}}v")
    raw = "" if value is None or value.text is None else value.text
    if kind == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError) as exc:
            raise _XlsxError("工作簿的共享文字索引无效。") from exc
    if kind == "b":
        raise _XlsxError("任务表格不能包含布尔值字段。")
    return raw


def parse_xlsx_bytes(content: bytes, filename: str = "tasks.xlsx") -> ImportResult:
    if len(content) > MAX_FILE_BYTES:
        return ImportResult(filename, (), (ImportIssue("file_too_large", "文件超过 1 MB，未读取。"),))
    if not content:
        return ImportResult(filename, (), (ImportIssue("empty_file", "文件为空，没有可预览的任务。"),))
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > MAX_ARCHIVE_MEMBERS or len(names) != len(set(names)):
                raise _XlsxError("工作簿结构异常，无法安全读取。")
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise _XlsxError("工作簿解压后过大，未读取。")
            if any(info.flag_bits & 0x1 for info in infos):
                raise _XlsxError("不支持加密工作簿。")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                string_root = _safe_xml(archive, "xl/sharedStrings.xml")
                shared_strings = [
                    "".join(part.text or "" for part in item.iter(f"{{{_MAIN_NS}}}t"))
                    for item in string_root.findall(f"{{{_MAIN_NS}}}si")
                ]
            sheet = _safe_xml(archive, _worksheet_member(archive))
            rows: list[list[str]] = []
            for row in sheet.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
                row_number = int(row.get("r", "0"))
                if row_number < 1 or row_number > 1000:
                    raise _XlsxError("工作表行数异常；最多支持 999 行任务和一行表头。")
                values: dict[int, str] = {}
                for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                    index = _column_index(cell.get("r", ""))
                    if index in values:
                        raise _XlsxError("工作表中存在重复单元格。")
                    values[index] = _cell_text(cell, shared_strings)
                if values:
                    rows.append([values.get(index, "") for index in range(max(values) + 1)])
    except (zipfile.BadZipFile, OSError, RuntimeError, OverflowError, ValueError) as exc:
        message = str(exc) if isinstance(exc, _XlsxError) else "工作簿格式无效或已损坏，无法安全读取。"
        return ImportResult(filename, (), (ImportIssue("invalid_xlsx", message),))
    if not rows:
        return ImportResult(filename, (), (ImportIssue("empty_file", "工作表为空，没有可预览的任务。"),))
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    result = parse_csv_bytes(output.getvalue().encode("utf-8"), filename)
    return result
