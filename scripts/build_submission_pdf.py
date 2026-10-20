"""Five-page submission brief using actual, explicitly labelled Qt renderings."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pdf/DeskCare_参赛项目说明_UI6.pdf"
SHOTS = ROOT / "build/ui6-final"
WIDTH = 508


def main():
    pdfmetrics.registerFont(TTFont("DeskCareCJK", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    common = dict(fontName="DeskCareCJK", wordWrap="CJK", textColor=colors.HexColor("#293E38"))
    styles = {
        "title": ParagraphStyle("title", **common, fontSize=28, leading=36, spaceAfter=12),
        "h1": ParagraphStyle("h1", **common, fontSize=20, leading=29, spaceAfter=15),
        "h2": ParagraphStyle("h2", **common, fontSize=12, leading=19, spaceBefore=11, spaceAfter=6),
        "body": ParagraphStyle("body", **common, fontSize=10.7, leading=17.5, spaceAfter=10),
        "small": ParagraphStyle("small", **common, fontSize=8.5, leading=13, spaceAfter=8),
        "cell": ParagraphStyle("cell", **common, fontSize=9.4, leading=14),
    }
    story = []

    def p(text, role="body"):
        story.append(Paragraph(text, styles[role]))

    def shot(filename, caption, width=WIDTH):
        image = Image(str(SHOTS / filename))
        image.drawHeight = image.imageHeight * width / image.imageWidth
        image.drawWidth = width
        story.extend([Spacer(1, 7), image, Spacer(1, 6)])
        p(caption, "small")

    def table(rows, widths):
        widget = Table([[Paragraph(cell, styles["cell"]) for cell in row] for row in rows],
                       colWidths=widths, repeatRows=1, hAlign="LEFT")
        widget.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9F1EC")),
            ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#D9E2DD")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.extend([widget, Spacer(1, 12)])

    p("DeskCare", "title")
    p("把今天的安排和电脑前的使用节奏放在一起", "h2")
    p("天猫 OPC 赛道参赛项目说明 · UI6 · 2026年10月20日", "small")
    p("DeskCare 是面向 Windows 学生与办公人群的本地桌面助手。它把今日任务、经授权的电脑使用概览和个人状态回顾连接起来，在用户选择的情境下给出可推迟、可跳过的休息提示。")
    shot("today.png", "当前 UI6 源码的真实 Qt 界面渲染。图中任务、时间和状态均为明确标注的虚构演示数据，不是用户研究结果。")
    p("使用门槛", "h2")
    p("不需要账号、模型或 API Key 就能使用基本流程；不开统计也能管理任务。Windows 便携目录解压后运行，完整演示另用隔离数据，不覆盖日常记录。")
    story.append(PageBreak())

    p("用户为什么需要它", "h1")
    p("典型场景是学生在浏览器和编程工具间完成作业，或办公用户在会议与专注工作间切换。待办、使用时间和提醒分散在不同工具里，固定时间通知未必适合当前安排。这是待验证的需求判断，不是已有访谈结论。")
    shot("usage.png", "使用统计界面实渲染。柱状图与类别图来自包内虚构数据；统计值表示有限活动估计，不是工作质量或健康评分。")
    p("一条可体验的路径", "h2")
    p("添加或导入任务并确认 → 自己选择工作情境 → 在愿意时开启有限统计 → 对提醒作出选择 → 一天结束查看本地回顾。任务是否完成、今天感觉如何，都由用户自己填写。")
    p("先验证真实价值", "h2")
    p("后续邀请自愿参与者独立走完整个流程，观察操作卡点和提醒打扰感，再比较固定间隔与情境提醒。没有这些证据前，不宣称已经提高效率或改善健康。")
    story.append(PageBreak())

    p("核心功能如何联动", "h1")
    table([
        ["模块", "输入与行为", "与其他模块的联系"],
        ["今日任务", "手工添加，或导入清单后核对草稿；状态由用户确认", "已确认的期限与完成操作进入提醒情境"],
        ["电脑使用与提醒", "授权后按日汇总活动；参考会议、专注等手动情境", "选择柔性提醒时机，保留推迟、跳过与时机反馈"],
        ["状态与回顾", "可选打卡；从已保存的任务、统计和提示记录生成日报周报", "缺数据就说明缺失，不凭应用推断任务或身体状态"],
    ], [88, 211, 209])
    shot("report.png", "UI6 日报实渲染：扩大行距、分开任务与状态，类别和应用使用独立明细。当前报告为本机事实模板，不是假装调用模型。", width=450)
    p("可选桌面伙伴", "h2")
    p("简洁面板支持快捷任务和情境操作，可右键切换吉祥物；三种日常表情对应当天主动保存的状态。形象是透明 PNG 切换，不是 Live2D。伙伴贴边和多屏体验仍需人工补验。")
    story.append(PageBreak())

    p("技术实现与验证证据", "h1")
    p("使用 Python 3.11/3.12、PySide6 Qt Widgets、SQLite 和 Win32 ctypes。采样、导入、任务、提醒策略与报告分层；测试用可替换时钟、模拟 provider 和临时数据库。PyInstaller 在 Windows 构建完整便携目录。")
    table([
        ["能力", "当前证据", "尚未证明的部分"],
        ["离线业务与界面", "全量 154 项自动测试通过；新增日报与双向样式切换回归", "不等于所有电脑、屏幕和长期运行都已通过"],
        ["Windows 实际运行", "UI6 隔离 EXE 启动、任务添加、双击编辑保存、日报显示与滚动", "托盘完整操作、伙伴贴边和右键实测仍需补验"],
        ["150% 缩放", "报告、状态菜单和伙伴相关 31 项回归通过", "干净第二台 Windows 与多屏矩阵未完成"],
        ["AI 适配器", "本地及云端解析接口、校验、请求确认和错误降级已有自动测试", "未配置或授权模型；本机服务未运行，未完成真实推理"],
    ], [96, 205, 207])
    p("创新点是连接关系", "h2")
    p("用用户确认的任务约束与手动情境选择提醒时机，再把反馈带入本地回顾。规则引擎不是训练模型，个性化效果尚待对照验证；模型输出仅是候选，不能直接写入任务或推断健康。")
    p("必要边界", "h2")
    p("统计、应用名称、状态和 AI 各自授权；不记录键入内容、窗口标题、网页地址或截图。云端只接收逐次确认的任务文字，不自动上传使用统计和状态。产品不是医学诊断或治疗工具。")
    p("本次验收以隔离演示实例和临时数据库为范围，未清除真实数据。便携包未签名，未验证八小时持续运行。", "small")
    story.append(PageBreak())

    p("竞争位置与下一步", "h1")
    p("Workrave 已提供休息提醒与统计，ActivityWatch 强调本地时间追踪，Stretchly 提供跨平台休息提醒。因此，计时、提醒和本地存储都不是 DeskCare 独有。值得验证的差别是任务约束、情境与回顾的联动，以及普通用户能否省心地使用。")
    p("商业模式仍是验证假设", "h2")
    p("优先保留免费基础任务、提醒与隐私管理，探索高级历史或外观付费。39 元每年、69 元一次性增强包只是待测价格，不是已售套餐。没有经核验的用户规模、付费收入或留存结果，也没有天猫商品接口、分佣或交易闭环。")
    p("提交之后的优先顺序", "h2")
    p("先补验托盘、伙伴边缘行为、干净 Windows 和长期运行；再用真实模型对照离线清单解析，记录遗漏、错误日期与修改成本。邀请 10 至 20 位自愿用户体验后，再决定定价、托管 AI 或更复杂动画。")
    p("技术与素材来源", "h2")
    p("应用基于 Python、Qt for Python、SQLite 与 PyInstaller，许可和版本说明随包提供。吉祥物原图由项目方提供，透明副本由图像工具辅助处理；正式商业使用前核验原图权利。项目源码未另行指定开源许可证，附源码供参赛评审与复现。")
    p("交付与资料入口", "h2")
    p('仓库：<link href="https://github.com/firefelixfu026/DeskCare" color="#285C4E">github.com/firefelixfu026/DeskCare</link>。网页和远端 HEAD 已核验可访问；远端不自动代表 UI6，最新代码以随附源码和校验清单为准。')
    p('竞品资料：<link href="https://workrave.org/">Workrave</link> · <link href="https://activitywatch.net/">ActivityWatch</link> · <link href="https://hovancik.net/stretchly/">Stretchly</link>。Qt 许可：<link href="https://doc.qt.io/qtforpython-6/licenses.html">官方说明</link>。核验日期为 2026年10月20日。', "small")
    p("随附 Windows 便携包、源码包、实际界面图、人工验收清单和两分钟演示脚本。赛事入口在本环境仅取得页面外壳，最新天猫 OPC 提交字段须由项目方在浏览器核对。", "small")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=52, rightMargin=52,
                            topMargin=42, bottomMargin=44, title="DeskCare 参赛项目说明", author="DeskCare")
    def footer(canvas, document):
        canvas.setFont("DeskCareCJK", 8)
        canvas.setFillColor(colors.HexColor("#76877E"))
        canvas.drawString(52, 24, "DeskCare  |  UI6  |  2026年10月20日")
        canvas.drawRightString(560, 24, str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__":
    main()
