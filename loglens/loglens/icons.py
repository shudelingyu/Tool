"""内置线性图标与品牌 Logo 加载。"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtSvg import QSvgRenderer

from .theme import ACCENT

_SVG_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round">'
)

_SVGS = {
    "folder": (
        '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.2l1.8 2H19a1.5 1.5 0 0 1 1.5 1.5v7.9A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>'
        '<path d="M3.5 9.5h17"/>'
    ),
    "export": (
        '<path d="M12 3.5v10.2"/>'
        '<path d="M8.4 10.2l3.6 3.6 3.6-3.6"/>'
        '<path d="M4.5 15.8v2.7A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5v-2.7"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="8.7"/>'
        '<path d="M9.5 9.2a2.6 2.6 0 0 1 5.1.6c0 1.5-1.4 1.9-2.2 2.6-.4.4-.5.8-.5 1.3"/>'
        '<circle cx="12" cy="16.9" r=".75" fill="{color}" stroke="none"/>'
    ),
    "search": (
        '<circle cx="10.6" cy="10.6" r="6.1"/>'
        '<path d="M15.2 15.2l4.2 4.2"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 7.4v4.9l3.2 1.9"/>'
    ),
    "reset": (
        '<path d="M4.3 9.6A8.1 8.1 0 1 1 4 14"/>'
        '<path d="M4.3 4.5v5.1h5.1"/>'
    ),
    "expand": (
        '<path d="M7 7l5 5 5-5"/>'
        '<path d="M7 12.4l5 5 5-5"/>'
    ),
    "collapse": (
        '<path d="M7 12.4l5-5 5 5"/>'
        '<path d="M7 17.4l5-5 5 5"/>'
    ),
    "panel-left": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.2"/>'
        '<path d="M9.6 4.5v15"/>'
    ),
    "panel-right": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.2"/>'
        '<path d="M14.4 4.5v15"/>'
    ),
    "copy": (
        '<rect x="8.6" y="8.6" width="11" height="11" rx="2"/>'
        '<path d="M15.5 8.6V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2.1"/>'
    ),
    "file": (
        '<path d="M6.8 3.5h6.7l4.2 4.2v12.1a1.7 1.7 0 0 1-1.7 1.7H6.8a1.7 1.7 0 0 1-1.7-1.7V5.2a1.7 1.7 0 0 1 1.7-1.7z"/>'
        '<path d="M13.5 3.7v4.2h4.2"/>'
    ),
    "warning": (
        '<path d="M12 4.2l8.4 15H3.6z"/>'
        '<path d="M12 9.5v4.2"/>'
        '<circle cx="12" cy="16.4" r=".75" fill="{color}" stroke="none"/>'
    ),
    "close": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "check": '<path d="M5 12.5l4.4 4.4L19 6.9"/>',
    "spark": (
        '<path d="M12 3.5l1.5 5.2 5.1 1.5-5.1 1.5L12 16.8l-1.5-5.1-5.1-1.5 5.1-1.5z"/>'
        '<path d="M18.5 16.5l.7 2.2 2.1.7-2.1.7-.7 2.2-.7-2.2-2.2-.7 2.2-.7z"/>'
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


def logo_pixmap(size: int) -> QPixmap:
    path = resource_path("assets/loglens.png")
    source = QPixmap(str(path))
    if source.isNull():
        source = QPixmap(size * 2, size * 2)
        source.fill(Qt.transparent)
        painter = QPainter(source)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor("#15233D"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, size * 2, size * 2, size * 0.3, size * 0.3)
        painter.setPen(QPen(QColor("#E8F5FF"), max(2, size // 10), Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(int(size * 0.55), int(size * 0.45), int(size * 0.95), int(size * 0.95))
        painter.end()
    scale = 2
    scaled = source.scaled(
        size * scale,
        size * scale,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(scale)
    return scaled


def app_icon() -> QIcon:
    path = resource_path("assets/loglens.ico")
    if path.exists():
        return QIcon(str(path))
    return QIcon(logo_pixmap(64))


def accent_icon(name: str, size: int = 18) -> QIcon:
    return icon(name, ACCENT, size)
