"""内置线性图标与品牌 Logo。"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PyQt5.QtSvg import QSvgRenderer

from .theme import ACCENT

_SVG_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round">'
)

_SVGS = {
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "trash": (
        '<path d="M4.4 7h15.2"/>'
        '<path d="M9.6 7V5.4a1.4 1.4 0 0 1 1.4-1.4h2a1.4 1.4 0 0 1 1.4 1.4V7"/>'
        '<path d="M6.6 7.2l.8 11a1.7 1.7 0 0 0 1.7 1.6h5.8a1.7 1.7 0 0 0 1.7-1.6l.8-11"/>'
        '<path d="M10.2 10.7v5.9"/><path d="M13.8 10.7v5.9"/>'
    ),
    "clear": (
        '<circle cx="12" cy="12" r="8.4"/>'
        '<path d="M9.2 9.2l5.6 5.6"/><path d="M14.8 9.2l-5.6 5.6"/>'
    ),
    "reset": (
        '<path d="M4.3 9.6A8.1 8.1 0 1 1 4 14"/>'
        '<path d="M4.3 4.5v5.1h5.1"/>'
    ),
    "fit": (
        '<path d="M4 9.2V5.2A1.2 1.2 0 0 1 5.2 4h4"/>'
        '<path d="M14.8 4h4A1.2 1.2 0 0 1 20 5.2v4"/>'
        '<path d="M20 14.8v4a1.2 1.2 0 0 1-1.2 1.2h-4"/>'
        '<path d="M9.2 20h-4A1.2 1.2 0 0 1 4 18.8v-4"/>'
        '<circle cx="12" cy="12" r="1.15" fill="{color}" stroke="none"/>'
    ),
    "grid": (
        '<rect x="4" y="4" width="16" height="16" rx="1.6"/>'
        '<path d="M4 9.4h16"/><path d="M4 14.6h16"/>'
        '<path d="M9.4 4v16"/><path d="M14.6 4v16"/>'
    ),
    "path": (
        '<path d="M4.6 18.4l4.4-6.3 3.6 3.1 6.8-8.6"/>'
        '<circle cx="4.8" cy="18.2" r="1.3" fill="{color}" stroke="none"/>'
        '<circle cx="19.1" cy="6.7" r="1.3" fill="{color}" stroke="none"/>'
    ),
    "tag": (
        '<path d="M11.4 4.4H5.9A1.5 1.5 0 0 0 4.4 5.9v5.5l8.5 8.5a1.5 1.5 0 0 0 2.1 0l5.4-5.4a1.5 1.5 0 0 0 0-2.1z"/>'
        '<circle cx="8.6" cy="8.6" r="1.2"/>'
    ),
    "copy": (
        '<rect x="8.6" y="8.6" width="11" height="11" rx="2"/>'
        '<path d="M15.5 8.6V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2.1"/>'
    ),
    "check": '<path d="M5 12.5l4.4 4.4L19 6.9"/>',
    "swap": (
        '<path d="M4.5 9h12.2"/><path d="M13.4 5.6L16.8 9l-3.4 3.4"/>'
        '<path d="M19.5 15H7.3"/><path d="M10.6 11.6L7.2 15l3.4 3.4"/>'
    ),
    "file": (
        '<path d="M6.8 3.5h6.7l4.2 4.2v12.1a1.7 1.7 0 0 1-1.7 1.7H6.8a1.7 1.7 0 0 1-1.7-1.7V5.2a1.7 1.7 0 0 1 1.7-1.7z"/>'
        '<path d="M13.5 3.7v4.2h4.2"/>'
    ),
    "robot": (
        '<circle cx="12" cy="6.2" r="2.4"/>'
        '<path d="M12 8.6v6"/>'
        '<path d="M6.8 11.2h10.4"/>'
        '<path d="M12 14.6l-3.2 5"/>'
        '<path d="M12 14.6l3.2 5"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="8.7"/>'
        '<path d="M9.5 9.2a2.6 2.6 0 0 1 5.1.6c0 1.5-1.4 1.9-2.2 2.6-.4.4-.5.8-.5 1.3"/>'
        '<circle cx="12" cy="16.9" r=".75" fill="{color}" stroke="none"/>'
    ),
    "axis": (
        '<path d="M5 19V5"/><path d="M5 19h14"/><path d="M5 19l7-7"/>'
    ),
    "vector": (
        '<path d="M5 19L18.4 5.6"/>'
        '<path d="M12.6 5.6h5.8v5.8"/>'
        '<circle cx="5" cy="19" r="1.5" fill="{color}" stroke="none"/>'
    ),
    "calc": (
        '<rect x="4.5" y="3.5" width="15" height="17" rx="2.2"/>'
        '<path d="M8 8h8"/>'
        '<path d="M8 12v.01M12 12v.01M16 12v.01"/>'
        '<path d="M8 16v.01M12 16v.01M16 16v.01"/>'
    ),
    "ruler": (
        '<path d="M4.5 15.5L15.5 4.5l4 4L8.5 19.5z"/>'
        '<path d="M8.5 11.5l1.6 1.6M11 9l1.6 1.6M13.5 6.5l1.6 1.6"/>'
    ),
    "camera": (
        '<rect x="3.5" y="7" width="17" height="12.5" rx="2.2"/>'
        '<path d="M8.5 7l1.4-2.4h4.2L15.5 7"/>'
        '<circle cx="12" cy="13.2" r="3.4"/>'
    ),
    "link": (
        '<path d="M10.4 13.6a4.2 4.2 0 0 0 5.9 0l2.1-2.1a4.2 4.2 0 0 0-5.9-5.9l-1.2 1.2"/>'
        '<path d="M13.6 10.4a4.2 4.2 0 0 0-5.9 0l-2.1 2.1a4.2 4.2 0 0 0 5.9 5.9l1.2-1.2"/>'
    ),
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#64748B", size: int = 18) -> QIcon:
    body = _SVGS.get(name)
    if body is None:
        return QIcon()
    svg = _SVG_HEADER.format(color=color) + body + "</svg>"
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def primary_icon(name: str, size: int = 16) -> QIcon:
    return icon(name, "#FFFFFF", size)


@lru_cache(maxsize=64)
def dot_icon(color: str, size: int = 12) -> QIcon:
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, size * scale - 2, size * scale - 2)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def logo_pixmap(size: int) -> QPixmap:
    path = resource_path("assets/poseview.png")
    source = QPixmap(str(path))
    if source.isNull():
        source = _fallback_logo(size * 2)
    scale = 2
    scaled = source.scaled(
        size * scale,
        size * scale,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(scale)
    return scaled


def _fallback_logo(pixel_size: int) -> QPixmap:
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(0, 0, pixel_size, pixel_size)
    gradient.setColorAt(0.0, QColor("#6366F1"))
    gradient.setColorAt(1.0, QColor("#312E81"))
    painter.setBrush(gradient)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, pixel_size, pixel_size), pixel_size * 0.24, pixel_size * 0.24)
    painter.setPen(QPen(QColor("#E0E7FF"), max(2.0, pixel_size / 26), Qt.SolidLine, Qt.RoundCap))
    origin = (pixel_size * 0.36, pixel_size * 0.70)
    painter.drawLine(
        int(origin[0]), int(origin[1]),
        int(pixel_size * 0.80), int(pixel_size * 0.80),
    )
    painter.drawLine(
        int(origin[0]), int(origin[1]),
        int(pixel_size * 0.36), int(pixel_size * 0.22),
    )
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    path = resource_path("assets/poseview.ico")
    if path.exists():
        return QIcon(str(path))
    return QIcon(logo_pixmap(64))


def accent_icon(name: str, size: int = 18) -> QIcon:
    return icon(name, ACCENT, size)
