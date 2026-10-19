"""Local PNG mascot surface; no model runtime or system observation."""

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QBitmap, QColor, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QWidget


ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "mascot"
VARIANTS = {"comfortable", "uncomfortable", "skip", "drag", "peek-left", "peek-right"}


def solid_region(pixmap):
    # Ignore nearly transparent extraction noise when measuring the artwork
    # and hit target. Default alpha dithering can turn alpha=1 into isolated
    # mask pixels across the entire original square canvas.
    mask = pixmap.toImage().createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither)
    return QRegion(QBitmap.fromImage(mask))


class MascotSurface(QWidget):
    """Draw supplied artwork without a rectangular window or hit target."""

    silhouette_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mascotSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("DeskCare 吉祥物")
        self.variant = "skip"
        self._cache = {}
        self._scaled = QPixmap()
        self._image_rect = QRect()
        self.hit_region = QRegion()

    @property
    def asset_available(self):
        return not self._load(self.variant).isNull()

    def _load(self, variant):
        if variant not in self._cache:
            pixmap = QPixmap(str(ASSET_ROOT / f"{variant}.png"))
            if not pixmap.isNull():
                bounds = solid_region(pixmap).boundingRect().adjusted(-2, -2, 2, 2).intersected(pixmap.rect())
                if not bounds.isEmpty():
                    pixmap = pixmap.copy(bounds)
            self._cache[variant] = pixmap
        return self._cache[variant]

    def set_variant(self, variant):
        if variant not in VARIANTS:
            raise ValueError("Unknown mascot artwork")
        if variant == self.variant and not self._scaled.isNull():
            return
        self.variant = variant
        self._layout_artwork()

    def _layout_artwork(self):
        source = self._load(self.variant)
        if source.isNull() or self.width() < 1 or self.height() < 1:
            self._scaled = QPixmap()
            self._image_rect = self.rect().adjusted(10, 10, -10, -10)
            self.hit_region = QRegion(self._image_rect, QRegion.RegionType.Ellipse)
        else:
            self._scaled = source.scaled(QSize(self.width(), self.height()),
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - self._scaled.width()) // 2
            if self.variant == "peek-left":
                x = 0
            elif self.variant == "peek-right":
                x = self.width() - self._scaled.width()
            self._image_rect = QRect(x, self.height() - self._scaled.height(),
                                     self._scaled.width(), self._scaled.height())
            self.hit_region = solid_region(self._scaled).translated(self._image_rect.topLeft())
        self.setMask(self.hit_region)
        self.update()
        self.silhouette_changed.emit()

    def resizeEvent(self, event):
        self._layout_artwork()
        super().resizeEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._scaled.isNull():
            painter.drawPixmap(self._image_rect.topLeft(), self._scaled)
        else:
            # A missing/corrupt optional asset must not make the helper
            # impossible to click or hide.
            painter.setBrush(QColor("#C9EBDD"))
            painter.setPen(QColor("#367A6C"))
            painter.drawEllipse(self._image_rect)
            painter.drawText(self._image_rect, Qt.AlignmentFlag.AlignCenter, "DeskCare")
        painter.end()
