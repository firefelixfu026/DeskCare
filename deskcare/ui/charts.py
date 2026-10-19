"""Small native charts for already-authorized, aggregated usage data."""

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QLineF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget


PALETTE = ("#347F70", "#77ACAA", "#E4B66A", "#879CCA", "#C18DAD", "#A2B583")


@dataclass(frozen=True)
class ChartEntry:
    label: str
    seconds: float | None


def duration(seconds: float) -> str:
    minutes = seconds / 60
    if minutes >= 60:
        return f"{int(minutes // 60)} 小时 {int(minutes % 60)} 分钟"
    return f"{minutes:.1f} 分钟"


class UsageChart(QWidget):
    """Animated bars/donut; missing observations remain distinct from zero."""

    def __init__(self, kind="columns", parent=None):
        super().__init__(parent)
        self.setObjectName("chartSurface")
        self.kind = kind
        self.entries: tuple[ChartEntry, ...] = ()
        self.empty_text = "有记录后，图表会在这里更新"
        self._progress = 1.0
        self._hits: list[tuple[QRectF, str]] = []
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(260)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._animate)
        self.setMinimumHeight(250)
        self.setMinimumWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName("电脑活动时间估计图")

    def _animate(self, value):
        self._progress = float(value)
        self.update()

    @property
    def empty_message(self):
        if self.entries and any(entry.seconds is not None for entry in self.entries):
            return "已有观测记录，当前活跃时间为 0 分钟"
        return self.empty_text

    def set_values(self, values, empty_text=None):
        entries = tuple(ChartEntry(str(name), None if seconds is None else max(0.0, float(seconds)))
                        for name, seconds in values)
        if empty_text is not None:
            self.empty_text = empty_text
        self.setAccessibleDescription("；".join(
            f"{entry.label}：{'无记录' if entry.seconds is None else duration(entry.seconds)}"
            for entry in entries
        ) or self.empty_text)
        if entries == self.entries:
            self.update()
            return
        self.animation.stop()
        self.entries = entries
        self.setMinimumHeight(max(250, len(entries) * 38 + 26) if self.kind == "bars" else 250)
        if self.isVisible() and any((entry.seconds or 0) > 0 for entry in entries):
            self.animation.setStartValue(0.0)
            self.animation.setEndValue(1.0)
            self.animation.start()
        else:
            self._progress = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        self._hits = []
        if not self.entries or not any((entry.seconds or 0) > 0 for entry in self.entries):
            painter.setPen(QColor("#79858A"))
            painter.drawText(self.rect().adjusted(20, 20, -20, -20),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.empty_message)
        elif self.kind == "donut":
            self._donut(painter)
        elif self.kind == "bars":
            self._bars(painter)
        else:
            self._columns(painter)
        painter.end()

    def _columns(self, painter):
        plot = QRectF(45, 24, self.width() - 65, self.height() - 67)
        maximum = max(entry.seconds or 0 for entry in self.entries)
        ceiling = max(60.0, maximum * 1.18)
        for fraction in (0, 0.5, 1):
            y = plot.bottom() - plot.height() * fraction
            painter.setPen(QPen(QColor("#E7EEED"), 1))
            painter.drawLine(QLineF(plot.left(), y, plot.right(), y))
            painter.setPen(QColor("#7D898D"))
            painter.drawText(QRectF(0, y - 9, 39, 18), Qt.AlignmentFlag.AlignRight,
                             f"{ceiling * fraction / 60:.0f}分")
        step = plot.width() / len(self.entries)
        for index, entry in enumerate(self.entries):
            height = (entry.seconds or 0) / ceiling * plot.height() * self._progress
            bar = QRectF(plot.left() + step * index + step * .22,
                         plot.bottom() - max(height, 3), step * .56, max(height, 3))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#DFE7E5" if entry.seconds is None else PALETTE[0]))
            painter.drawRoundedRect(bar, 5, 5)
            painter.setPen(QColor("#67777B"))
            axis_label = entry.label.rsplit("/", 1)[-1] + "日" if step < 48 and "/" in entry.label else entry.label
            painter.drawText(QRectF(plot.left() + step * index, plot.bottom() + 10, step, 23),
                             Qt.AlignmentFlag.AlignCenter, axis_label)
            tip = f"{entry.label}：{'无记录' if entry.seconds is None else duration(entry.seconds)}"
            self._hits.append((QRectF(plot.left() + step * index, plot.top(), step, plot.height()), tip))

    def _bars(self, painter):
        maximum = max(entry.seconds or 0 for entry in self.entries)
        label_width = min(145, self.width() * .3)
        value_width = 125
        track_width = max(20, self.width() - label_width - value_width - 22)
        for index, entry in enumerate(self.entries):
            y = 10 + index * 38
            painter.setPen(QColor("#344C50"))
            text = painter.fontMetrics().elidedText(entry.label, Qt.TextElideMode.ElideRight, int(label_width - 8))
            painter.drawText(QRectF(0, y, label_width - 8, 26), Qt.AlignmentFlag.AlignVCenter, text)
            track = QRectF(label_width, y + 7, track_width, 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#EDF2F1"))
            painter.drawRoundedRect(track, 6, 6)
            painter.setBrush(QColor(PALETTE[index % len(PALETTE)]))
            fill = QRectF(track)
            fill.setWidth(max(2, track_width * (entry.seconds or 0) / maximum * self._progress))
            painter.drawRoundedRect(fill, 6, 6)
            painter.setPen(QColor("#607278"))
            painter.drawText(QRectF(label_width + track_width + 12, y, value_width, 26),
                             Qt.AlignmentFlag.AlignVCenter, duration(entry.seconds or 0))
            self._hits.append((QRectF(0, y, self.width(), 32), f"{entry.label}：{duration(entry.seconds or 0)}"))

    def _donut(self, painter):
        total = sum(entry.seconds or 0 for entry in self.entries)
        side = min(180, self.width() * .47, self.height() - 40)
        ring = QRectF(20, (self.height() - side) / 2, side, side)
        stroke = side * .17
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#EDF2F1"), stroke))
        painter.drawEllipse(ring.adjusted(stroke/2, stroke/2, -stroke/2, -stroke/2))
        angle = 90 * 16
        for index, entry in enumerate(self.entries):
            span = (entry.seconds or 0) / total * 360 * 16 * self._progress
            painter.setPen(QPen(QColor(PALETTE[index % len(PALETTE)]), stroke))
            painter.drawArc(ring.adjusted(stroke/2, stroke/2, -stroke/2, -stroke/2), int(angle), -int(span))
            angle -= span
        painter.setPen(QColor("#234B46"))
        number_font = QFont(self.font())
        number_font.setPointSize(18)
        number_font.setBold(True)
        painter.setFont(number_font)
        painter.drawText(ring.adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, f"{total / 60:.1f}")
        painter.setFont(self.font())
        painter.setPen(QColor("#81918E"))
        painter.drawText(ring.adjusted(0, 38, 0, 0), Qt.AlignmentFlag.AlignCenter, "活跃分钟")
        left = ring.right() + 20
        for index, entry in enumerate(self.entries):
            y = max(8, (self.height() - len(self.entries) * 32) / 2) + index * 32
            painter.setBrush(QColor(PALETTE[index % len(PALETTE)]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(left, y + 7, 8, 8))
            painter.setPen(QColor("#4B6463"))
            text = f"{entry.label}  {(entry.seconds or 0) / total:.0%}"
            painter.drawText(QRectF(left + 16, y, self.width() - left - 16, 25), Qt.AlignmentFlag.AlignVCenter, text)
            self._hits.append((QRectF(left, y, self.width() - left, 30), f"{entry.label}：{duration(entry.seconds or 0)}"))

    def mouseMoveEvent(self, event):
        for rect, text in self._hits:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)
