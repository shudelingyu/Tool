"""PoseView 视觉主题：颜色、字体与全局样式表。"""

from __future__ import annotations

from functools import lru_cache

from PyQt5.QtGui import QFont, QFontDatabase

ACCENT = "#4F46E5"
ACCENT_DARK = "#4338CA"
ACCENT_SOFT = "#EEF2FF"
BACKGROUND = "#F3F5FB"
CARD = "#FFFFFF"
BORDER = "#E4E9F2"
TEXT = "#0F172A"
TEXT_SECONDARY = "#475569"
MUTED = "#64748B"
FAINT = "#94A3B8"
SUCCESS = "#047857"
DANGER = "#DC2626"
WARNING = "#B45309"

DARK_BG = "#070B14"
DARK_PANEL = "#0F1A2E"
DARK_LINE = "#1E293B"
DARK_TEXT = "#CBD5E1"


@lru_cache(maxsize=1)
def ui_family() -> str:
    families = set(QFontDatabase().families())
    for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Arial"):
        if candidate in families:
            return candidate
    return "Arial"


@lru_cache(maxsize=1)
def mono_family() -> str:
    families = set(QFontDatabase().families())
    for candidate in ("Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New"):
        if candidate in families:
            return candidate
    return "Courier New"


def font(size: float, weight: int = QFont.Normal) -> QFont:
    """size 以 96 DPI 下的磅值为设计基准，换算为逻辑像素。"""
    value = QFont(ui_family())
    value.setPixelSize(max(1, round(size * 4 / 3)))
    value.setWeight(weight)
    return value


def mono_font(size: float, weight: int = QFont.Normal) -> QFont:
    value = QFont(mono_family())
    value.setPixelSize(max(1, round(size * 4 / 3)))
    value.setStyleHint(QFont.Monospace)
    value.setWeight(weight)
    return value


def app_stylesheet() -> str:
    return f"""
    * {{
        font-family: "{ui_family()}";
        font-size: 12px;
        color: {TEXT};
    }}

    QMainWindow, QWidget#Root {{
        background: {BACKGROUND};
    }}
    QDialog#RobotDialog, QDialog#CalcDialog, QDialog#PoseInputDialog,
    QDialog#VectorInputDialog, QDialog#UrdfDialog, QDialog#MergeDialog {{
        background: {BACKGROUND};
    }}
    QLabel#DialogTitle {{
        font-size: 16px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#DialogHint {{
        font-size: 11px;
        color: {MUTED};
    }}

    QComboBox {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 4px 8px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: #CBD5E1;
    }}
    QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox QAbstractItemView {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_SOFT};
        selection-color: {ACCENT_DARK};
        outline: none;
    }}
    QLineEdit#PoseInput {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 6px 9px;
    }}
    QLineEdit#PoseInput:focus {{
        border-color: {ACCENT};
    }}
    QPlainTextEdit#RawData {{
        background: #F8FAFC;
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 4px 6px;
        color: #334155;
        selection-background-color: #C7D2FE;
        selection-color: #1E293B;
    }}
    QDoubleSpinBox {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 3px 5px;
    }}
    QDoubleSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QCheckBox {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
        spacing: 4px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1px solid #CBD5E1;
        background: #FFFFFF;
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:disabled {{
        background: #F1F5F9;
        border-color: #E2E8F0;
    }}
    QSlider#JointSlider::groove:horizontal {{
        height: 4px;
        background: #E2E8F0;
        border-radius: 2px;
    }}
    QSlider#JointSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
    QSlider#JointSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: #FFFFFF;
        border: 2px solid {ACCENT};
    }}

    QFrame#Header {{
        background: {CARD};
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#AppTitle {{
        font-size: 17px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#AppSubtitle {{
        font-size: 11px;
        color: {MUTED};
    }}
    QFrame#Card {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QFrame#ViewCard {{
        background: {DARK_BG};
        border: 1px solid #16233B;
        border-radius: 12px;
    }}
    QFrame#ViewBar {{
        background: {DARK_PANEL};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border-bottom: 1px solid #1B2A44;
    }}
    QLabel#ViewTitle {{
        color: #94A3B8;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#SectionTitle {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#CardHint {{
        font-size: 11px;
        color: {MUTED};
    }}
    QLabel#Badge {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
        border-radius: 9px;
        padding: 1px 8px;
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#CountBadge {{
        background: #F1F5F9;
        color: {MUTED};
        border-radius: 9px;
        padding: 1px 8px;
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#PoseName {{
        font-size: 12px;
        font-weight: 600;
        color: {ACCENT_DARK};
    }}
    QLabel#MiniTitle {{
        font-size: 11px;
        font-weight: 600;
        color: {MUTED};
    }}
    QLabel#ValueKey {{
        font-size: 11px;
        color: {FAINT};
    }}
    QLabel#ValueNum {{
        font-size: 12px;
        color: {TEXT};
    }}
    QFrame#InfoBox {{
        background: #F8FAFC;
        border: 1px solid #EDF2F9;
        border-radius: 9px;
    }}
    QSplitter#BodySplitter::handle {{
        background: transparent;
        width: 8px;
    }}
    QTreeWidget#DataTree {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 4px 3px;
        outline: none;
    }}
    QTreeWidget#DataTree::item {{
        min-height: 22px;
        padding: 3px 4px;
        border-radius: 6px;
        color: {TEXT_SECONDARY};
    }}
    QTreeWidget#DataTree::item:hover {{
        background: #F8FAFC;
    }}
    QTreeWidget#DataTree::item:selected {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
    }}
    QTreeWidget#DataTree::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1px solid #CBD5E1;
        background: #FFFFFF;
    }}
    QTreeWidget#DataTree::indicator:hover {{
        border-color: {ACCENT};
    }}
    QTreeWidget#DataTree::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    QTabWidget#CalcTabs::pane {{
        border: 1px solid {BORDER};
        border-radius: 10px;
        background: transparent;
        top: -1px;
    }}
    QTabWidget#CalcTabs QTabBar::tab {{
        background: #F1F5F9;
        color: {MUTED};
        border: 1px solid #E9EEF6;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 7px 14px;
        margin-right: 3px;
        font-size: 11px;
    }}
    QTabWidget#CalcTabs QTabBar::tab:selected {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
        border-color: #C7D2FE;
        font-weight: 600;
    }}
    QTableWidget#TrajectoryTable {{
        background: #F8FAFC;
        border: 1px solid #EDF2F9;
        border-radius: 8px;
        gridline-color: #E9EEF6;
        selection-background-color: {ACCENT_SOFT};
    }}
    QTableWidget#TrajectoryTable QHeaderView::section {{
        background: #F1F5F9;
        color: {MUTED};
        border: none;
        border-bottom: 1px solid #E9EEF6;
        padding: 5px 6px;
        font-size: 11px;
        font-weight: 600;
    }}

    QPlainTextEdit#MatrixEditor {{
        background: #0F172A;
        color: #E2E8F0;
        border: 1px solid #1E293B;
        border-radius: 9px;
        padding: 10px 12px;
        selection-background-color: {ACCENT};
        selection-color: #FFFFFF;
    }}
    QPlainTextEdit#MatrixEditor:focus {{
        border: 1px solid {ACCENT};
    }}

    QPushButton#Primary {{
        background: {ACCENT};
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background: {ACCENT_DARK};
    }}
    QPushButton#Primary:pressed {{
        background: #3730A3;
    }}
    QPushButton#Ghost {{
        background: #FFFFFF;
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 7px 12px;
    }}
    QPushButton#Ghost:hover {{
        background: #F8FAFC;
        border-color: #CBD5E1;
        color: {TEXT};
    }}
    QPushButton#Ghost:pressed {{
        background: #F1F5F9;
    }}
    QPushButton#Ghost:disabled {{
        color: #CBD5E1;
        border-color: #EEF2F8;
    }}

    QToolButton#ViewTool {{
        color: {DARK_TEXT};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 5px 9px;
        font-size: 11px;
    }}
    QToolButton#ViewTool:hover {{
        background: #1E293B;
        color: #F1F5F9;
    }}
    QToolButton#ViewTool:checked {{
        background: #312E81;
        color: #C7D2FE;
        border-color: #4338CA;
    }}
    QToolButton#ModeTab {{
        background: #F1F5F9;
        color: {MUTED};
        border: 1px solid #E9EEF6;
        border-radius: 7px;
        padding: 5px 4px;
        font-size: 11px;
    }}
    QToolButton#ModeTab:hover {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
    }}
    QToolButton#ModeTab:checked {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
        border-color: #C7D2FE;
        font-weight: 600;
    }}
    QToolButton#IconButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 3px;
    }}
    QToolButton#IconButton:hover {{
        background: #F1F5F9;
        border-color: #E2E8F0;
    }}

    QListWidget#PoseList {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget#PoseList::item {{
        padding: 7px 6px;
        border-radius: 7px;
        color: {TEXT_SECONDARY};
    }}
    QListWidget#PoseList::item:hover {{
        background: #F8FAFC;
    }}
    QListWidget#PoseList::item:selected {{
        background: {ACCENT_SOFT};
        color: {ACCENT_DARK};
    }}
    QListWidget#PoseList::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1px solid #CBD5E1;
        background: #FFFFFF;
    }}
    QListWidget#PoseList::indicator:hover {{
        border-color: {ACCENT};
    }}
    QListWidget#PoseList::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #D5DDEA;
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #B8C4D6;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: #D5DDEA;
        border-radius: 4px;
        min-width: 28px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    QSplitter::handle {{
        background: transparent;
        width: 10px;
    }}
    QSplitter::handle:hover {{
        background: transparent;
    }}

    QStatusBar {{
        background: {CARD};
        border-top: 1px solid {BORDER};
        color: {MUTED};
        font-size: 11px;
    }}
    QStatusBar QLabel {{
        color: {MUTED};
        font-size: 11px;
    }}

    QToolTip {{
        background: #0F172A;
        color: #E2E8F0;
        border: 1px solid #1E293B;
        padding: 5px 7px;
    }}
    """
