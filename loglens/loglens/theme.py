"""LogLens 视觉主题：颜色、字体与全局样式表。"""

from __future__ import annotations

from functools import lru_cache

from PyQt5.QtGui import QColor, QFontDatabase

ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
BACKGROUND = "#F4F7FB"
CARD = "#FFFFFF"
BORDER = "#E6EBF3"
TEXT = "#0F172A"
TEXT_SECONDARY = "#475569"
MUTED = "#64748B"
FAINT = "#94A3B8"

LEVEL_COLORS = {
    "TRACE": "#8B9AAD",
    "DEBUG": "#64748B",
    "INFO": "#2563EB",
    "WARNING": "#D97706",
    "ERROR": "#DC2626",
    "CRITICAL": "#9333EA",
    "OTHER": "#7C8798",
}

LEVEL_BACKGROUNDS = {
    "TRACE": "#F1F5F9",
    "DEBUG": "#F1F5F9",
    "INFO": "#EFF6FF",
    "WARNING": "#FFF7ED",
    "ERROR": "#FEF2F2",
    "CRITICAL": "#F5F3FF",
    "OTHER": "#F4F6F9",
}

LEVEL_CHIP_CHECKED = {
    "TRACE": ("#F1F5F9", "#64748B", "#CBD5E1"),
    "DEBUG": ("#F1F5F9", "#475569", "#CBD5E1"),
    "INFO": ("#EFF6FF", "#1D4ED8", "#BFDBFE"),
    "WARNING": ("#FFF7ED", "#B45309", "#FED7AA"),
    "ERROR": ("#FEF2F2", "#B91C1C", "#FECACA"),
    "CRITICAL": ("#F5F3FF", "#7E22CE", "#DDD6FE"),
    "OTHER": ("#F4F6F9", "#475569", "#CBD5E1"),
}


def level_color(level: str) -> str:
    return LEVEL_COLORS.get(level, LEVEL_COLORS["OTHER"])


def level_background(level: str) -> str:
    return LEVEL_BACKGROUNDS.get(level, LEVEL_BACKGROUNDS["OTHER"])


def qcolor(value: str, alpha: int | None = None) -> QColor:
    color = QColor(value)
    if alpha is not None:
        color.setAlpha(alpha)
    return color


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

    QFrame#Header {{
        background: {CARD};
        border-bottom: 1px solid {BORDER};
    }}
    QFrame#Toolbar {{
        background: {CARD};
        border-bottom: 1px solid #EEF2F8;
    }}
    QFrame#FilterBar {{
        background: {CARD};
        border-bottom: 1px solid {BORDER};
    }}
    QDialog#ContextDialog {{
        background: {BACKGROUND};
    }}
    QTreeWidget#ContextTree {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 8px;
        outline: none;
    }}
    QPlainTextEdit#ContextText {{
        background: #FBFDFF;
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 8px;
        color: #1E293B;
        selection-background-color: #BFDBFE;
    }}
    QSpinBox#SpanSpin {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 0 4px;
        color: #334155;
        font-size: 11px;
    }}
    QSpinBox#SpanSpin:focus {{
        border-color: #93C5FD;
    }}
    QLabel#AppTitle {{
        font-size: 16px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#AppSubtitle {{
        font-size: 10px;
        color: {FAINT};
    }}
    QLabel#SectionLabel {{
        font-size: 11px;
        font-weight: 600;
        color: {FAINT};
    }}
    QLabel#CardTitle {{
        font-size: 12px;
        font-weight: 700;
        color: #334155;
    }}
    QLabel#CardHint {{
        font-size: 10px;
        color: {FAINT};
    }}
    QLabel#Muted {{
        color: {FAINT};
        font-size: 11px;
    }}
    QLabel#SourceName {{
        font-size: 13px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#SourcePath {{
        font-size: 10px;
        color: {FAINT};
    }}
    QLabel#SourceMeta {{
        font-size: 10px;
        color: {MUTED};
    }}
    QLabel#EncodingPill {{
        background: #ECFDF5;
        color: #047857;
        border: 1px solid #A7F3D0;
        border-radius: 8px;
        padding: 2px 7px;
        font-size: 9px;
        font-weight: 700;
    }}
    QLabel#StatValue {{
        font-size: 17px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#StatCaption {{
        font-size: 9px;
        color: {FAINT};
    }}
    QLabel#DetailLevel {{
        border-radius: 9px;
        padding: 2px 9px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#DetailChip {{
        background: #F1F5F9;
        color: #475569;
        border-radius: 5px;
        padding: 2px 7px;
        font-size: 10px;
    }}
    QLabel#DetailMeta {{
        color: {FAINT};
        font-size: 10px;
    }}
    QLabel#BannerText {{
        color: #92400E;
        font-size: 11px;
    }}

    QFrame#FileChip {{
        background: #F4F7FB;
        border: 1px solid {BORDER};
        border-radius: 9px;
    }}
    QFrame#Card {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QFrame#WarningBanner {{
        background: #FFFBEB;
        border-bottom: 1px solid #FDE68A;
    }}
    QFrame#FieldBar {{
        background: #F8FAFC;
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#FieldBarHint {{
        color: {FAINT};
        font-size: 10px;
    }}
    QComboBox#FieldCombo {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 7px;
        padding: 0 26px 0 10px;
        color: #334155;
        font-size: 11px;
    }}
    QComboBox#FieldCombo:hover {{
        border-color: #CBD5E1;
    }}
    QComboBox#FieldCombo:focus {{
        border-color: #93C5FD;
    }}
    QComboBox#FieldCombo::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox#FieldCombo QAbstractItemView {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        padding: 4px;
        outline: none;
        selection-background-color: #EFF6FF;
        selection-color: {ACCENT_DARK};
    }}
    QFrame#Separator {{
        background: #EDF1F7;
    }}

    QPushButton {{
        outline: none;
    }}
    QPushButton#Primary {{
        background: {ACCENT};
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 0 16px;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background: {ACCENT_DARK};
    }}
    QPushButton#Primary:pressed {{
        background: #1E40AF;
    }}
    QPushButton#Primary:disabled {{
        background: #C7D2FE;
        color: #F8FAFC;
    }}
    QPushButton#Ghost {{
        background: transparent;
        color: #475569;
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 0 12px;
        font-weight: 600;
    }}
    QPushButton#Ghost:hover {{
        background: #F4F7FB;
        border-color: #D9E2EE;
    }}
    QPushButton#Ghost:pressed {{
        background: #EAF0F8;
    }}
    QPushButton#Ghost:disabled {{
        color: #CBD5E1;
        border-color: #EEF2F7;
    }}

    QToolButton#IconButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 6px;
    }}
    QToolButton#IconButton:hover {{
        background: #F1F5F9;
    }}
    QToolButton#IconButton:pressed {{
        background: #E2E8F0;
    }}
    QToolButton#IconButton:checked {{
        background: #EAF2FF;
    }}
    QToolButton#Toggle {{
        background: #F4F7FB;
        border: 1px solid transparent;
        border-radius: 7px;
        color: {MUTED};
        font-family: "{mono_family()}";
        font-size: 11px;
        font-weight: 700;
    }}
    QToolButton#Toggle:hover {{
        background: #EDF3FA;
    }}
    QToolButton#Toggle:checked {{
        background: #EFF6FF;
        border-color: #BFDBFE;
        color: {ACCENT_DARK};
    }}

    QLineEdit#Search {{
        background: #F4F7FB;
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 0 10px;
        color: {TEXT};
        selection-background-color: #BFDBFE;
    }}
    QLineEdit#Search:focus {{
        background: #FFFFFF;
        border-color: #93C5FD;
    }}
    QLineEdit#Search[invalid="true"] {{
        background: #FFF7F7;
        border-color: #FCA5A5;
    }}

    QFrame#Segment {{
        background: #F1F5F9;
        border-radius: 8px;
    }}
    QPushButton#SegmentButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 0 12px;
        color: {MUTED};
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#SegmentButton:hover {{
        color: #334155;
    }}
    QPushButton#SegmentButton:checked {{
        background: #FFFFFF;
        border-color: #E2E8F0;
        color: {ACCENT_DARK};
    }}

    QPushButton#LevelChip {{
        background: #F4F7FB;
        border: 1px solid transparent;
        border-radius: 12px;
        padding: 0 10px;
        font-size: 10px;
        font-weight: 600;
        color: {MUTED};
    }}
    QPushButton#LevelChip:hover {{
        background: #EDF3FA;
    }}
    QPushButton#LevelChip:checked {{
        background: #EFF6FF;
        border-color: #BFDBFE;
        color: {ACCENT_DARK};
    }}
    QPushButton#LevelChip[chipLevel="TRACE"]:checked {{
        background: {LEVEL_CHIP_CHECKED["TRACE"][0]};
        color: {LEVEL_CHIP_CHECKED["TRACE"][1]};
        border-color: {LEVEL_CHIP_CHECKED["TRACE"][2]};
    }}
    QPushButton#LevelChip[chipLevel="DEBUG"]:checked {{
        background: {LEVEL_CHIP_CHECKED["DEBUG"][0]};
        color: {LEVEL_CHIP_CHECKED["DEBUG"][1]};
        border-color: {LEVEL_CHIP_CHECKED["DEBUG"][2]};
    }}
    QPushButton#LevelChip[chipLevel="INFO"]:checked {{
        background: {LEVEL_CHIP_CHECKED["INFO"][0]};
        color: {LEVEL_CHIP_CHECKED["INFO"][1]};
        border-color: {LEVEL_CHIP_CHECKED["INFO"][2]};
    }}
    QPushButton#LevelChip[chipLevel="WARNING"]:checked {{
        background: {LEVEL_CHIP_CHECKED["WARNING"][0]};
        color: {LEVEL_CHIP_CHECKED["WARNING"][1]};
        border-color: {LEVEL_CHIP_CHECKED["WARNING"][2]};
    }}
    QPushButton#LevelChip[chipLevel="ERROR"]:checked {{
        background: {LEVEL_CHIP_CHECKED["ERROR"][0]};
        color: {LEVEL_CHIP_CHECKED["ERROR"][1]};
        border-color: {LEVEL_CHIP_CHECKED["ERROR"][2]};
    }}
    QPushButton#LevelChip[chipLevel="CRITICAL"]:checked {{
        background: {LEVEL_CHIP_CHECKED["CRITICAL"][0]};
        color: {LEVEL_CHIP_CHECKED["CRITICAL"][1]};
        border-color: {LEVEL_CHIP_CHECKED["CRITICAL"][2]};
    }}
    QPushButton#LevelChip[chipLevel="OTHER"]:checked {{
        background: {LEVEL_CHIP_CHECKED["OTHER"][0]};
        color: {LEVEL_CHIP_CHECKED["OTHER"][1]};
        border-color: {LEVEL_CHIP_CHECKED["OTHER"][2]};
    }}
    QPushButton#ModuleChip {{
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 12px;
        padding: 0 10px;
        font-size: 10px;
        font-weight: 600;
        color: {ACCENT_DARK};
    }}
    QPushButton#ModuleChip:hover {{
        background: #DBEAFE;
    }}

    QTreeWidget#LogTree {{
        background: #FFFFFF;
        border: none;
        outline: none;
        alternate-background-color: #FFFFFF;
        selection-background-color: transparent;
    }}
    QTreeWidget#LogTree::item {{
        border: none;
    }}
    QTreeWidget#LogTree::item:selected {{
        background: transparent;
    }}
    QHeaderView::section {{
        background: #F8FAFC;
        color: {MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 0 12px;
        font-size: 10px;
        font-weight: 600;
    }}

    QTreeWidget#FieldTable {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QTreeWidget#FieldTable::item {{
        border-bottom: 1px solid #F1F5F9;
        padding-left: 2px;
        color: {TEXT_SECONDARY};
    }}
    QTreeWidget#FieldTable::item:selected {{
        background: #EFF6FF;
        color: {ACCENT_DARK};
    }}

    QPlainTextEdit#RawLog {{
        background: #F8FAFC;
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 8px;
        selection-background-color: #BFDBFE;
    }}

    QProgressBar#LoadProgress {{
        background: #E9EFF7;
        border: none;
        border-radius: 4px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar#LoadProgress::chunk {{
        background: {ACCENT};
        border-radius: 4px;
    }}

    QSplitter::handle {{
        background: transparent;
    }}
    QSplitter::handle:hover {{
        background: #DBEAFE;
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #CBD5E1;
        min-height: 28px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94A3B8;
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
        background: #CBD5E1;
        min-width: 28px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #94A3B8;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    QStatusBar {{
        background: #FFFFFF;
        border-top: 1px solid {BORDER};
        color: {MUTED};
        min-height: 26px;
    }}
    QStatusBar::item {{
        border: none;
    }}
    QStatusBar QLabel {{
        color: {MUTED};
        font-size: 10px;
        padding: 0 7px;
    }}

    QToolTip {{
        background: #0F172A;
        color: #F8FAFC;
        border: none;
        padding: 6px 8px;
        font-size: 11px;
    }}

    QMenu {{
        background: #FFFFFF;
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 7px 22px 7px 14px;
        border-radius: 5px;
        color: #334155;
    }}
    QMenu::item:selected {{
        background: #EFF6FF;
        color: {ACCENT_DARK};
    }}
    QMenu::separator {{
        height: 1px;
        background: #EDF1F7;
        margin: 5px 8px;
    }}

    QDialog#HelpDialog {{
        background: #FFFFFF;
    }}
    QTextBrowser#HelpText {{
        background: #FFFFFF;
        border: none;
        color: #334155;
        font-size: 12px;
    }}
    QTextBrowser#HelpText h2 {{
        color: {TEXT};
    }}
    """
