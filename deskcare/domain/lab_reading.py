"""Verified-report arithmetic and sourced CBC vocabulary, never diagnosis."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata


RESULTS_SOURCE = "https://medlineplus.gov/lab-tests/how-to-understand-your-lab-results/"
CBC_SOURCE = "https://medlineplus.gov/lab-tests/complete-blood-count-cbc/"
# Short original paraphrases, not clinical interpretation of a person's results.
CBC = {
    "WBC": ("白细胞计数", ("白细胞计数", "白细胞", "WBC"), "白细胞参与免疫防御。此项表示白细胞的数量。"),
    "RBC": ("红细胞计数", ("红细胞计数", "红细胞", "RBC"), "红细胞负责运送氧气。此项表示红细胞的数量。"),
    "HGB": ("血红蛋白", ("血红蛋白浓度", "血红蛋白", "HGB", "Hb"), "血红蛋白是红细胞中携带氧气的蛋白质。"),
    "HCT": ("红细胞比容", ("红细胞压积", "红细胞比容", "HCT"), "表示红细胞在血液中所占的比例。"),
    "MCV": ("平均红细胞体积", ("平均红细胞体积", "红细胞平均体积", "MCV"), "表示红细胞的平均大小。"),
    "PLT": ("血小板计数", ("血小板计数", "血小板", "PLT"), "血小板参与凝血，有助于止血。此项表示血小板的数量。"),
}
UNITS = {
    "WBC": {"10^9/l", "10^3/ul"}, "PLT": {"10^9/l", "10^3/ul"},
    "RBC": {"10^12/l", "10^6/ul"}, "HGB": {"g/l", "g/dl"},
    "HCT": {"l/l", "%"}, "MCV": {"fl"},
}
STATUS = {"high": "高于报告范围", "low": "低于报告范围", "within": "在报告范围内", "unknown": "暂不能对照"}
NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
QUESTIONS = {
    "context": "这些结果还需要结合哪些病史、用药或近期情况来理解？",
    "repeat": "是否需要复查？如果需要，何时复查、是否应在同一家实验室进行？",
    "preparation": "空腹、近期活动或用药等准备因素，是否可能影响这次结果的理解？",
    "range": "报告提供的参考范围，是否适用于我的年龄等具体情况？",
    "symptoms": "我还需要向医生补充哪些症状或身体变化？",
}


def marker_code(name):
    key = re.sub(r"[\s*＊]", "", name).casefold()
    for code, (_, aliases, _) in CBC.items():
        if key in {alias.casefold() for alias in aliases}:
            return code
    return None


def unit_key(unit):
    unit = unit.replace("10⁹", "10^9").replace("10¹²", "10^12").replace("10³", "10^3").replace("10⁶", "10^6")
    key = unicodedata.normalize("NFKC", unit).lower().replace("µ", "u").replace("μ", "u").replace("×", "x")
    return re.sub(r"\s", "", key).removeprefix("x")


def numeric(value):
    if not isinstance(value, str) or len(value) > 24 or not re.fullmatch(NUMBER, value.strip()):
        return None
    try:
        result = Decimal(value.strip())
        return result if result.is_finite() and result >= 0 and result <= Decimal("1e12") else None
    except InvalidOperation:
        return None


def reference_bounds(text):
    if not isinstance(text, str) or len(text) > 64:
        return None
    text = unicodedata.normalize("NFKC", text).strip().replace("−", "-").replace("—", "-").replace("–", "-")
    match = re.fullmatch(rf"({NUMBER})\s*(?:-|~|～|至)\s*({NUMBER})", text)
    if match:
        low, high = numeric(match[1]), numeric(match[2])
        return (low, high, True, True) if low is not None and high is not None and low <= high else None
    match = re.fullmatch(rf"(<=|>=|<|>|≤|≥)\s*({NUMBER})", text)
    if match:
        bound = numeric(match[2])
        if bound is not None:
            return ((None, bound, False, match[1] in {"<=", "≤"}) if match[1] in {"<", "<=", "≤"}
                    else (bound, None, match[1] in {">=", "≥"}, False))
    return None


@dataclass(frozen=True)
class LabRow:
    name: str
    result: str
    unit: str
    reference: str
    confirmed: bool = False

    @property
    def code(self):
        return marker_code(self.name)

    def check(self):
        if not self.confirmed:
            return "unknown", "尚未核对原件，不作对照。"
        if self.code is None:
            return "unknown", "此指标暂未纳入已核对的血常规说明，不自动解释。"
        if unit_key(self.unit) not in UNITS[self.code]:
            return "unknown", "单位缺失或暂不支持，请按原件核对，不自动换算。"
        value, bounds = numeric(self.result), reference_bounds(self.reference)
        if value is None:
            return "unknown", "数值含不明确字符或比较符号，不猜测真实结果。"
        if bounds is None:
            return "unknown", "报告范围缺失、分人群或格式不明确，不使用通用范围补齐。"
        low, high, low_closed, high_closed = bounds
        if low is not None and (value < low or (value == low and not low_closed)):
            return "low", "仅表示低于你核对的报告范围，不代表已确诊。"
        if high is not None and (value > high or (value == high and not high_closed)):
            return "high", "仅表示高于你核对的报告范围，不代表已确诊。"
        return "within", "在这份报告的范围内，也不等于排除所有健康问题。"


def validate_rows(rows):
    if not 1 <= len(rows) <= 40:
        raise ValueError("请保留 1–40 项指标，分报告核对。")
    for row in rows:
        if (not isinstance(row, LabRow) or not row.name.strip() or len(row.name) > 60
                or len(row.result) > 40 or len(row.unit) > 40 or len(row.reference) > 100
                or any("\n" in field or "\r" in field for field in (row.name, row.result, row.unit, row.reference))):
            raise ValueError("指标字段长度或格式不正确，请逐项核对。")
    selected = [row.code for row in rows if row.confirmed and row.code]
    if len(set(selected)) != len(selected):
        raise ValueError("已核对项中存在重复指标，请一次核对同一份报告的一组结果。")


def parse_lab_text(text):
    """Conservative line parser: do not infer missing columns or OCR digits."""
    if len(text) > 40000:
        raise ValueError("这一页文字过多，请只保留本次要核对的指标。")
    rows, unmatched = [], 0
    aliases = sorted({alias for _, names, _ in CBC.values() for alias in names}, key=len, reverse=True)
    pattern = re.compile(r"^\s*(?:\d+[.、\s]+)?[*＊]?\s*(" + "|".join(map(re.escape, aliases)) + r")(?![A-Za-z])", re.I)
    for line in text.splitlines():
        # Windows OCR may insert spaces between Chinese letters in a label.
        line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", line.strip())
        match = pattern.match(line)
        if not match:
            if re.search(r"\d", line): unmatched += 1
            continue
        code = marker_code(match[1])
        tail = line[match.end():].lstrip(" ：:\t")
        result = re.match(rf"([<>≤≥]?\s*{NUMBER})(?:\s*(?:[↑↓]|[HL](?![A-Za-z/])))?(?!\d)", tail)
        if not result:
            unmatched += 1
            continue
        rest = tail[result.end():].strip()
        ref = re.search(rf"((?:{NUMBER})\s*(?:-|~|～|至|—|–)\s*(?:{NUMBER})|(?:<=|>=|<|>|≤|≥)\s*{NUMBER})\s*$", rest)
        unit = rest[:ref.start()].strip() if ref else rest
        unit = re.sub(r"^(?:[↑↓]|[HL](?=\s|$))\s*", "", unit).strip()
        rows.append(LabRow(CBC[code][0], result[1].replace(" ", ""), unit, ref[1] if ref else ""))
        if len(rows) >= 40:
            break
    return tuple(rows), unmatched


def render_reading(rows, *, focus_codes=None, question_ids=None):
    validate_rows(rows)
    selected = [row for row in rows if row.confirmed]
    if not selected:
        raise ValueError("请先对照原件，勾选已核对的指标。")
    lines = ["检验单辅助阅读", "只对照你已核对的这一份报告；不是诊断或病情严重程度评估。", ""]
    for row in selected:
        state, note = row.check()
        lines += [f"{row.name}　{row.result} {row.unit}", f"报告范围：{row.reference or '未提供'}　·　{STATUS[state]}"]
        if row.code:
            lines.append(CBC[row.code][2])
        lines += [note, ""]
    if focus_codes:
        lines += ["AI 选择先阅读的项目（不是严重程度排序）：", "、".join(CBC[code][0] for code in focus_codes), ""]
    lines += ["可以带给医生的问题："]
    lines += ["· " + QUESTIONS[key] for key in (question_ids or ("range", "context", "repeat"))]
    lines += ["", "报告中若已有危急值提示或医护要求立即联系，请优先按其指示处理，不要等待此工具。",
              "不同实验室的范围和单位可能不同；缺失范围不会补猜，也不做跨报告趋势判断。", "",
              "说明来源（一般知识，不是针对你的诊断）：", "MedlinePlus — Complete Blood Count (CBC)", CBC_SOURCE,
              "MedlinePlus — How to Understand Your Lab Results", RESULTS_SOURCE]
    return "\n".join(lines)
