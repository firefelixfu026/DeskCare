"""Small code-native sidebar symbols matching the application's palette."""

from math import cos, sin, pi

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def navigation_icon(kind):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#598477"), 1.7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "tasks":
        for y in (6, 12, 18):
            painter.drawLine(9, y, 21, y)
            painter.drawRoundedRect(QRectF(2, y - 2, 4, 4), 1, 1)
    elif kind == "usage":
        painter.drawLine(3, 21, 22, 21)
        for x, height in ((5, 8), (11, 17), (17, 12)):
            painter.drawRoundedRect(QRectF(x, 20 - height, 3, height), 1, 1)
    elif kind == "status":
        path = QPainterPath(QPointF(2, 12))
        for x, y in ((6, 12), (9, 5), (13, 19), (17, 10), (20, 12), (23, 12)):
            path.lineTo(x, y)
        painter.drawPath(path)
    elif kind == "report":
        painter.drawRoundedRect(QRectF(4, 2, 16, 20), 3, 3)
        for y, end in ((8, 16), (12, 16), (16, 12)):
            painter.drawLine(8, y, end, y)
    else:
        painter.drawEllipse(QRectF(5, 5, 14, 14))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        for index in range(8):
            angle = index * pi / 4
            painter.drawLine(QPointF(12 + cos(angle) * 8, 12 + sin(angle) * 8),
                             QPointF(12 + cos(angle) * 10, 12 + sin(angle) * 10))
    painter.end()
    return QIcon(pixmap)
