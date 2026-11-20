"""LogLens 主窗口：拖拽导入、分类视图、搜索、统计、详情与导出。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5 import sip
from PyQt5.QtCore import QModelIndex, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextBrowser,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __app_title__, __version__
from .analysis import (
    Query,
    SearchError,
    Summary,
    build_groups,
    build_pattern,
    export_entries,
    filter_entries,
    summarize,
)
from .icons import app_icon, icon, logo_pixmap
from .parser import (
    LARGE_FILE_WARN_BYTES,
    LEVELS,
    ParseCancelled,
    ParseResult,
    parse_file,
)
from .theme import ACCENT, FAINT, MUTED, app_stylesheet
from .widgets import (
    EXPAND_BUDGET,
    PER_GROUP_LIMIT,
    ROLE_ENTRY,
    ROLE_GROUP,
    ROLE_GROUP_ENTRIES,
    ROLE_GROUP_HINT,
    ROLE_GROUP_KEY,
    ROLE_GROUP_LEVEL,
    ROLE_GROUP_POPULATED,
    ROLE_GROUP_SHARE,
    ROLE_GROUP_SHOWN,
    ROLE_NOTICE,
    DetailPanel,
    DropOverlay,
    ElidedLabel,
    ContextDialog,
    LevelFilterBar,
    LoadingState,
    LogTree,
    MessageState,
    StatsSidebar,
    TimeRangeDialog,
    Toast,
    build_entry_item,
    format_count,
    human_size,
)


CONTEXT_WINDOW_SECONDS = 30


def _startup_directory() -> str:
    """文件对话框的默认目录：优先当前启动目录，其次程序所在目录。"""

    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd())
    except OSError:
        pass
    if getattr(sys, "frozen", False):
        try:
            candidates.append(Path(sys.executable).resolve().parent)
        except OSError:
            pass
    else:
        candidates.append(Path(__file__).resolve().parent.parent)
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return str(candidate)
        except OSError:
            continue
    return str(Path.home())


class ParseWorker(QThread):
    """后台解析线程，支持协作式取消。"""
    progressed = pyqtSignal(int, int, int)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        path: Path,
        parent=None,
        *,
        time_start: Optional[datetime] = None,
        time_end: Optional[datetime] = None,
    ):
        super().__init__(parent)
        self.path = path
        self.time_start = time_start
        self.time_end = time_end
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401
        try:
            result = parse_file(
                self.path,
                progress=lambda read, total, entries: self.progressed.emit(
                    read, total, entries
                ),
                should_cancel=lambda: self._cancel,
                time_start=self.time_start,
                time_end=self.time_end,
            )
        except ParseCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - 展示给用户
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(__app_title__)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(940, 620)
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.setStyleSheet(app_stylesheet())

        self._result: Optional[ParseResult] = None
        self._base_result: Optional[ParseResult] = None
        self._range_result: Optional[ParseResult] = None
        self._range_bounds: Optional[
            tuple[Optional[datetime], Optional[datetime]]
        ] = None
        self._range_previous: Optional[
            tuple[Optional[datetime], Optional[datetime]]
        ] = None
        self._summary: Optional[Summary] = None
        self._matched = []
        self._query = Query()
        self._active_levels = set(LEVELS)
        self._module_filter: Optional[str] = None
        self._time_start = None
        self._time_end = None
        self._view_mode = "level"
        self._tree_mode = "level"
        self._field_name: Optional[str] = None
        self._group_state: dict[str, dict[str, bool]] = {}
        self._selected_entry = None
        self._context_dialog: Optional[ContextDialog] = None
        self._noresult_mode = "reset"
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(260)
        self._filter_timer.timeout.connect(self._refresh_now)

        self._workers: set[ParseWorker] = set()
        self._worker: Optional[ParseWorker] = None
        self._load_token = 0
        self._last_dir = _startup_directory()
        self._splitter_sizes: dict[str, list[int]] = {}
        self._suppress_search = False

        self._build_ui()
        self._install_shortcuts()
        self._reset_to_empty()
        self._center_on_screen()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._build_toolbar())
        self.level_filter = LevelFilterBar()
        self.level_filter.activeLevelsChanged.connect(self._on_levels_changed)
        self.level_filter.moduleFilterCleared.connect(self._on_module_cleared)
        self.level_filter.timeFilterRequested.connect(self.open_time_filter)
        root_layout.addWidget(self.level_filter)
        root_layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

        self._status = QStatusBar()
        self._status.setSizeGripEnabled(False)
        self.setStatusBar(self._status)
        self._status_msg = QLabel("就绪")
        self._status.addWidget(self._status_msg, 1)
        self._status_encoding = QLabel("编码 —")
        self._status_total = QLabel("0 条")
        self._status_matched = QLabel("匹配 0")
        self._status_time = QLabel("解析 —")
        self._status_version = QLabel(f"v{__version__}")
        for label in (
            self._status_encoding,
            self._status_total,
            self._status_matched,
            self._status_time,
            self._status_version,
        ):
            self._status.addPermanentWidget(label)

        self._toast = Toast(self)
        self._drop_overlay = DropOverlay(self)
        self._drop_overlay.setGeometry(self.rect())

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(12)

        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setPixmap(logo_pixmap(32))
        layout.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title = QLabel("LogLens")
        title.setObjectName("AppTitle")
        subtitle = QLabel("日志分析器")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addSpacing(10)

        self._file_chip = QFrame()
        self._file_chip.setObjectName("FileChip")
        self._file_chip.setFixedHeight(34)
        chip_layout = QHBoxLayout(self._file_chip)
        chip_layout.setContentsMargins(9, 0, 10, 0)
        chip_layout.setSpacing(7)
        self._file_chip_icon = QLabel()
        self._file_chip_icon.setFixedSize(16, 16)
        self._file_chip_icon.setPixmap(icon("file", ACCENT, 15).pixmap(15, 15))
        self._file_chip_name = ElidedLabel("", Qt.ElideMiddle)
        self._file_chip_name.setFixedWidth(176)
        self._file_chip_name.setStyleSheet("color:#475569;font-size:10.5px;")
        chip_layout.addWidget(self._file_chip_icon)
        chip_layout.addWidget(self._file_chip_name)
        self._file_chip.setVisible(False)
        layout.addWidget(self._file_chip)
        layout.addStretch(1)

        self._open_btn = QPushButton("打开日志")
        self._open_btn.setObjectName("Primary")
        self._open_btn.setIcon(icon("folder", "#FFFFFF", 16))
        self._open_btn.setIconSize(QSize(16, 16))
        self._open_btn.setFixedHeight(36)
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.setToolTip("打开日志文件 (Ctrl+O)")
        self._open_btn.clicked.connect(self.open_dialog)
        layout.addWidget(self._open_btn)

        self._export_btn = QPushButton("导出")
        self._export_btn.setObjectName("Ghost")
        self._export_btn.setIcon(icon("export", "#475569", 16))
        self._export_btn.setIconSize(QSize(16, 16))
        self._export_btn.setFixedHeight(36)
        self._export_btn.setCursor(Qt.PointingHandCursor)
        self._export_btn.setToolTip("导出当前筛选结果 (Ctrl+E)")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self.export_dialog)
        layout.addWidget(self._export_btn)

        help_btn = QToolButton()
        help_btn.setObjectName("IconButton")
        help_btn.setIcon(icon("help", MUTED, 18))
        help_btn.setFixedSize(34, 34)
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.setToolTip("使用说明 (F1)")
        help_btn.clicked.connect(self.show_help)
        layout.addWidget(help_btn)

        separator = QFrame()
        separator.setObjectName("Separator")
        separator.setFixedSize(1, 24)
        layout.addSpacing(2)
        layout.addWidget(separator)
        layout.addSpacing(2)

        self._stats_toggle = QToolButton()
        self._stats_toggle.setObjectName("IconButton")
        self._stats_toggle.setIcon(icon("panel-left", MUTED, 18))
        self._stats_toggle.setFixedSize(34, 34)
        self._stats_toggle.setCheckable(True)
        self._stats_toggle.setChecked(True)
        self._stats_toggle.setCursor(Qt.PointingHandCursor)
        self._stats_toggle.setToolTip("显示 / 隐藏统计面板")
        self._stats_toggle.toggled.connect(self._on_stats_toggled)
        layout.addWidget(self._stats_toggle)

        self._detail_toggle = QToolButton()
        self._detail_toggle.setObjectName("IconButton")
        self._detail_toggle.setIcon(icon("panel-right", MUTED, 18))
        self._detail_toggle.setFixedSize(34, 34)
        self._detail_toggle.setCheckable(True)
        self._detail_toggle.setChecked(True)
        self._detail_toggle.setCursor(Qt.PointingHandCursor)
        self._detail_toggle.setToolTip("显示 / 隐藏详情面板")
        self._detail_toggle.toggled.connect(self._on_detail_toggled)
        layout.addWidget(self._detail_toggle)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(54)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索日志内容、模块、时间或字段…")
        self.search.setClearButtonEnabled(False)
        self.search.addAction(icon("search", FAINT, 16), QLineEdit.LeadingPosition)
        self._clear_action = self.search.addAction(
            icon("close", FAINT, 14), QLineEdit.TrailingPosition
        )
        self._clear_action.setToolTip("清除搜索")
        self._clear_action.setVisible(False)
        self._clear_action.triggered.connect(self.search.clear)
        self.search.setFixedHeight(36)
        self.search.setMinimumWidth(240)
        self.search.setMaximumWidth(560)
        self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search.setToolTip("支持关键词搜索，Ctrl+F 聚焦")
        self.search.textChanged.connect(self._on_search_changed)
        self.search.returnPressed.connect(self._refresh_now)
        layout.addWidget(self.search, 1)

        self._case_toggle = QToolButton()
        self._case_toggle.setObjectName("Toggle")
        self._case_toggle.setText("Aa")
        self._case_toggle.setCheckable(True)
        self._case_toggle.setFixedSize(36, 36)
        self._case_toggle.setCursor(Qt.PointingHandCursor)
        self._case_toggle.setToolTip("区分大小写")
        self._case_toggle.toggled.connect(self._on_search_mode_changed)
        layout.addWidget(self._case_toggle)

        self._regex_toggle = QToolButton()
        self._regex_toggle.setObjectName("Toggle")
        self._regex_toggle.setText(".*")
        self._regex_toggle.setCheckable(True)
        self._regex_toggle.setFixedSize(36, 36)
        self._regex_toggle.setCursor(Qt.PointingHandCursor)
        self._regex_toggle.setToolTip("使用正则表达式")
        self._regex_toggle.toggled.connect(self._on_search_mode_changed)
        layout.addWidget(self._regex_toggle)

        self._reset_btn = QToolButton()
        self._reset_btn.setObjectName("IconButton")
        self._reset_btn.setIcon(icon("reset", MUTED, 17))
        self._reset_btn.setFixedSize(34, 34)
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.setToolTip("重置搜索与筛选 (Ctrl+L)")
        self._reset_btn.clicked.connect(self.reset_filters)
        layout.addWidget(self._reset_btn)
        layout.addStretch(1)

        segment = QFrame()
        segment.setObjectName("Segment")
        segment.setFixedHeight(34)
        segment_layout = QHBoxLayout(segment)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(2)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_buttons: dict[str, QPushButton] = {}
        for mode, label, tooltip in (
            ("level", "按级别", "按日志级别分组"),
            ("module", "按模块", "按模块名称分组"),
            ("time", "按时间", "按时间区间分组"),
            ("field", "按字段", "按关键字段的值分组"),
        ):
            button = QPushButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setFixedHeight(28)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, value=mode: self.set_view_mode(value))
            self._view_group.addButton(button)
            segment_layout.addWidget(button)
            self._view_buttons[mode] = button
        self._view_buttons["level"].setChecked(True)
        layout.addWidget(segment)
        layout.addSpacing(6)

        expand_btn = QToolButton()
        expand_btn.setObjectName("IconButton")
        expand_btn.setIcon(icon("expand", MUTED, 18))
        expand_btn.setFixedSize(32, 32)
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setToolTip("全部展开 (Ctrl+Shift+E)")
        expand_btn.clicked.connect(self.expand_all)
        layout.addWidget(expand_btn)

        collapse_btn = QToolButton()
        collapse_btn.setObjectName("IconButton")
        collapse_btn.setIcon(icon("collapse", MUTED, 18))
        collapse_btn.setFixedSize(32, 32)
        collapse_btn.setCursor(Qt.PointingHandCursor)
        collapse_btn.setToolTip("全部折叠 (Ctrl+Shift+W)")
        collapse_btn.clicked.connect(self.collapse_all)
        layout.addWidget(collapse_btn)
        return toolbar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QHBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(8)
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        self.sidebar = StatsSidebar()
        self.sidebar.setMaximumWidth(390)
        self.sidebar.moduleClicked.connect(self._on_module_clicked)
        self.sidebar.fieldActivated.connect(self._on_field_activated)
        self._splitter.addWidget(self.sidebar)

        center = QFrame()
        center.setObjectName("Card")
        center.setMinimumWidth(320)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._banner = QFrame()
        self._banner.setObjectName("WarningBanner")
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(14, 7, 14, 7)
        banner_layout.setSpacing(8)
        banner_icon = QLabel()
        banner_icon.setPixmap(icon("warning", "#D97706", 15).pixmap(15, 15))
        self._banner_label = QLabel("")
        self._banner_label.setObjectName("BannerText")
        self._banner_label.setWordWrap(True)
        banner_layout.addWidget(banner_icon, 0, Qt.AlignTop)
        banner_layout.addWidget(self._banner_label, 1)
        self._banner.setVisible(False)
        center_layout.addWidget(self._banner)

        self._field_bar = QFrame()
        self._field_bar.setObjectName("FieldBar")
        self._field_bar.setFixedHeight(38)
        field_layout = QHBoxLayout(self._field_bar)
        field_layout.setContentsMargins(14, 0, 14, 0)
        field_layout.setSpacing(8)
        field_title = QLabel("按字段分组")
        field_title.setObjectName("SectionLabel")
        self._field_combo = QComboBox()
        self._field_combo.setObjectName("FieldCombo")
        self._field_combo.setFixedHeight(28)
        self._field_combo.setMinimumWidth(150)
        self._field_combo.setMaximumWidth(300)
        self._field_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._field_combo.currentTextChanged.connect(self._on_field_changed)
        field_hint = QLabel("按字段值统计")
        field_hint.setObjectName("FieldBarHint")
        field_layout.addWidget(field_title)
        field_layout.addWidget(self._field_combo)
        field_layout.addWidget(field_hint)
        field_layout.addStretch(1)
        self._field_bar.setVisible(False)
        center_layout.addWidget(self._field_bar)

        self._stack = QStackedWidget()
        self._empty_state = MessageState(
            "拖入日志文件开始分析",
            "支持 TXT / LOG / JSONL 等任意文本日志，\n"
            "自动识别 UTF-8、GBK、UTF-16 编码。",
            "选择日志文件",
            use_logo=True,
            primary=True,
        )
        self._empty_state.actionTriggered.connect(self.open_dialog)
        self._loading_state = LoadingState()
        self._loading_state.cancelRequested.connect(self._cancel_loading)
        self._noresult_state = MessageState(
            "没有匹配的日志",
            "尝试调整关键词、级别或模块筛选，\n或重置全部条件。",
            "重置筛选",
        )
        self._noresult_state.actionTriggered.connect(self._on_noresult_action)
        self.tree = LogTree()
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.itemExpanded.connect(self._populate_group)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        self._stack.addWidget(self._empty_state)
        self._stack.addWidget(self._loading_state)
        self._stack.addWidget(self._noresult_state)
        self._stack.addWidget(self.tree)
        center_layout.addWidget(self._stack, 1)
        self._center = center
        self._splitter.addWidget(center)

        self.detail_panel = DetailPanel()
        self.detail_panel.setMaximumWidth(470)
        self.detail_panel.toast.connect(self.show_toast)
        self._splitter.addWidget(self.detail_panel)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([286, 780, 360])
        self._splitter.splitterMoved.connect(
            lambda *_: QTimer.singleShot(0, self._apply_responsive)
        )
        return content

    def _install_shortcuts(self) -> None:
        bindings = (
            ("Ctrl+O", self.open_dialog),
            ("Ctrl+E", self.export_dialog),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+L", self.reset_filters),
            ("Ctrl+Shift+E", self.expand_all),
            ("Ctrl+Shift+W", self.collapse_all),
            ("F1", self.show_help),
        )
        for sequence, slot in bindings:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(slot)
            self.addAction(action)

        shortcut = QShortcut(QKeySequence("Esc"), self.search)
        shortcut.setContext(Qt.WidgetShortcut)
        shortcut.activated.connect(self.search.clear)

        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.tree)
        copy_shortcut.setContext(Qt.WidgetShortcut)
        copy_shortcut.activated.connect(self.copy_selected_raw)

    # ------------------------------------------------------------------
    # 布局与状态
    # ------------------------------------------------------------------

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(1440, max(self.minimumWidth(), int(available.width() * 0.9)))
        height = min(920, max(self.minimumHeight(), int(available.height() * 0.88)))
        self.resize(width, height)
        self.move(available.center() - self.rect().center())

    def _reset_to_empty(self) -> None:
        self._close_context_dialog()
        self._base_result = None
        self._range_result = None
        self._range_bounds = None
        self._range_previous = None
        self._stack.setCurrentWidget(self._empty_state)
        self.tree.clear()
        self._banner.setVisible(False)
        self.sidebar.clear()
        self.level_filter.set_counts({}, set(LEVELS))
        self.level_filter.set_module_filter(None)
        self._time_start = None
        self._time_end = None
        self.level_filter.set_time_filter(None, None)
        self._file_chip.setVisible(False)
        self._export_btn.setEnabled(False)
        self._detail_toggle.setChecked(True)
        self.detail_panel.clear()
        self._selected_entry = None
        self._field_name = None
        self._field_bar.setVisible(False)
        self._field_combo.blockSignals(True)
        self._field_combo.clear()
        self._field_combo.blockSignals(False)
        self._view_mode = "level"
        self._tree_mode = "level"
        self._view_buttons["level"].setChecked(True)
        self._status_msg.setText("就绪 · 拖入日志文件或点击“打开日志”")
        self._status_encoding.setText("编码 —")
        self._status_total.setText("0 条")
        self._status_matched.setText("匹配 0")
        self._status_time.setText("解析 —")
        self.setWindowTitle(__app_title__)

    def _apply_responsive(self) -> None:
        width = self.tree.viewport().width()
        if width <= 0:
            return
        self.tree.setColumnHidden(2, width < 600)
        self.tree.setColumnHidden(1, width < 470)
        if self._file_chip.isVisible():
            self._file_chip_name.setFixedWidth(120 if self.width() < 1120 else 176)
        self.tree.schedule_layout_refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast._place()
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.setGeometry(self.rect())
        QTimer.singleShot(0, self._apply_responsive)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_context_dialog()
        for worker in list(self._workers):
            worker.cancel()
        for worker in list(self._workers):
            worker.wait(3000)
        super().closeEvent(event)

    def _on_stats_toggled(self, checked: bool) -> None:
        self._set_panel_visible(self.sidebar, checked, "sidebar")
        self._stats_toggle.setIcon(icon("panel-left", ACCENT if checked else MUTED, 18))

    def _on_detail_toggled(self, checked: bool) -> None:
        self._set_panel_visible(self.detail_panel, checked, "detail")
        self._detail_toggle.setIcon(icon("panel-right", ACCENT if checked else MUTED, 18))
        if checked:
            if self._selected_entry is not None:
                self.detail_panel.set_entry(self._selected_entry, self._query)
            QTimer.singleShot(0, self._apply_responsive)

    def _set_panel_visible(self, panel: QWidget, visible: bool, key: str) -> None:
        if panel.isVisible() == visible:
            return
        if not visible:
            self._splitter_sizes[key] = self._splitter.sizes()
        panel.setVisible(visible)
        if visible:
            saved = self._splitter_sizes.get(key)
            if saved and 0 not in saved:
                self._splitter.setSizes(saved)
        QTimer.singleShot(0, self._apply_responsive)

    def _focus_search(self) -> None:
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def _ensure_detail_visible(self) -> None:
        if not self._detail_toggle.isChecked():
            self._detail_toggle.setChecked(True)
        if self._selected_entry is not None:
            self.detail_panel.set_entry(self._selected_entry, self._query)

    # ------------------------------------------------------------------
    # 公共状态（同时便于自动化测试）
    # ------------------------------------------------------------------

    @property
    def result(self) -> Optional[ParseResult]:
        return self._result

    @property
    def summary(self) -> Optional[Summary]:
        return self._summary

    @property
    def matched_entries(self):
        return list(self._matched)

    @property
    def is_loading(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    # ------------------------------------------------------------------
    # 拖拽
    # ------------------------------------------------------------------

    @staticmethod
    def _paths_from_mime(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if url.isLocalFile():
                local = Path(url.toLocalFile())
                if local.is_file():
                    paths.append(str(local))
        return paths

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._drop_overlay.show_overlay()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_overlay.hide_overlay()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_overlay.hide_overlay()
        paths = self._paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            self.show_toast("未识别到可读取的日志文件", "error")
            return
        event.acceptProposedAction()
        if len(paths) > 1:
            self.show_toast("一次仅支持一个文件，已导入第一个", "info")
        self.load_file(paths[0])

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def open_dialog(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "打开日志文件",
            self._last_dir,
            "日志文件 (*.log *.txt *.json *.jsonl *.out *.trace *.csv);;"
            "所有文件 (*.*)",
        )
        if not path:
            return
        self._last_dir = str(Path(path).parent)
        self.load_file(path)

    def load_file(self, path: str, *, confirm_large: bool = True) -> bool:
        target = Path(path)
        if not target.exists() or not target.is_file():
            self.show_toast("文件不存在或不可读", "error")
            return False
        try:
            size = target.stat().st_size
        except OSError as exc:
            self.show_toast(f"读取文件失败：{exc}", "error")
            return False
        if confirm_large and size > LARGE_FILE_WARN_BYTES:
            answer = QMessageBox.question(
                self,
                "加载较大的文件",
                f"文件大小 {human_size(size)}，加载可能需要较长时间。\n是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False

        self._last_dir = str(target.parent)
        self._range_previous = None
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        if self._filter_timer.isActive():
            self._filter_timer.stop()

        self._load_token += 1
        token = self._load_token
        self._banner.setVisible(False)
        self._loading_state.begin(target.name)
        self._stack.setCurrentWidget(self._loading_state)
        self._export_btn.setEnabled(False)
        self._status_msg.setText(f"正在解析 {target.name} …")

        worker = ParseWorker(target, self)
        worker.progressed.connect(
            lambda read, total, entries, t=token: self._on_progress(
                t, read, total, entries
            )
        )
        worker.succeeded.connect(lambda result, t=token: self._on_loaded(t, result))
        worker.failed.connect(lambda message, t=token: self._on_load_failed(t, message))
        worker.cancelled.connect(lambda t=token: self._on_load_cancelled(t))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._workers.add(worker)
        self._worker = worker
        worker.start()
        return True

    def _cancel_loading(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._status_msg.setText("正在取消加载…")

    def _on_worker_finished(self, worker: ParseWorker) -> None:
        self._workers.discard(worker)
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()

    def _on_progress(self, token: int, read: int, total: int, entries: int) -> None:
        if token != self._load_token:
            return
        self._loading_state.set_progress(read, total, entries)

    def _on_loaded(self, token: int, result: ParseResult) -> None:
        if token != self._load_token:
            return
        self._apply_result(result)

    def _on_load_failed(self, token: int, message: str) -> None:
        if token != self._load_token:
            return
        reverted = self._revert_range_filter()
        self._status_msg.setText("加载失败")
        self.show_toast("加载失败：" + message[:120], "error")
        self._restore_page_after_load()
        if reverted:
            self._refresh_now()
        QMessageBox.warning(self, "无法加载日志", message)

    def _on_load_cancelled(self, token: int) -> None:
        if token != self._load_token:
            return
        reverted = self._revert_range_filter()
        self._status_msg.setText("已取消加载")
        self.show_toast("已取消本次加载", "info")
        self._restore_page_after_load()
        if reverted:
            self._refresh_now()

    def _restore_page_after_load(self) -> None:
        self._export_btn.setEnabled(bool(self._matched))
        if self._result is None:
            self._stack.setCurrentWidget(self._empty_state)
        elif not self._result.entries:
            self._show_empty_file_state()
            self._stack.setCurrentWidget(self._noresult_state)
        elif self._matched:
            self._stack.setCurrentWidget(self.tree)
        else:
            self._show_noresult_state()
            self._stack.setCurrentWidget(self._noresult_state)

    def _apply_result(self, result: ParseResult) -> None:
        self._base_result = result
        self._range_result = None
        self._range_bounds = None
        self._range_previous = None
        self._close_context_dialog()
        self._result = result
        self._summary = None
        self._matched = []
        self._suppress_search = True
        self.search.clear()
        self._suppress_search = False
        self._clear_action.setVisible(False)
        self._set_search_invalid(False)
        self._active_levels = set(LEVELS)
        self._module_filter = None
        self.level_filter.set_module_filter(None)
        self._time_start = None
        self._time_end = None
        self.level_filter.set_time_filter(None, None)
        self._field_name = None
        self._field_bar.setVisible(False)
        self._field_combo.blockSignals(True)
        self._field_combo.clear()
        self._field_combo.blockSignals(False)
        self._view_mode = "level"
        self._tree_mode = "level"
        self._view_buttons["level"].setChecked(True)
        self._group_state.clear()
        self._query = Query()
        self._selected_entry = None
        self.detail_panel.clear()
        self.tree.clear()

        warnings = self._update_source_metadata(result, reset_levels=True)
        self._refresh_now()
        if result.entries:
            self.show_toast(
                f"已加载 {format_count(result.entry_count)} 条日志 · "
                f"{result.encoding_label} · {result.duration:.2f}s",
                "warning" if warnings else "success",
            )
        else:
            self.show_toast("文件为空，未发现可解析的文本", "warning")

    def _update_source_metadata(
        self,
        result: ParseResult,
        *,
        note: str = "",
        reset_levels: bool = False,
    ) -> list[str]:
        self._file_chip.setVisible(True)
        self._file_chip_name.setText(result.path.name)
        self._file_chip_name.setToolTip(str(result.path))
        self.setWindowTitle(f"{result.path.name} · {__app_title__}")
        self.sidebar.set_result(result)
        self.level_filter.set_file_time_span(result.source_time_range_text)
        if reset_levels:
            self.level_filter.set_counts(result.level_counts, set(LEVELS))
        else:
            self.level_filter.set_counts(result.level_counts)
        self.level_filter.set_time_filter(self._time_start, self._time_end)

        warnings: list[str] = []
        if note:
            warnings.append(note)
        if result.truncated:
            warnings.append(result.truncation_reason)
        if result.truncated_entries:
            warnings.append(
                f"{format_count(result.truncated_entries)} 条超长日志已截断"
            )
        self._banner_label.setText("；".join(warnings))
        self._banner.setVisible(bool(warnings))

        self._status_msg.setText(
            "已加载所选时间范围" if note else f"已加载 {result.path.name}"
        )
        self._status_encoding.setText(f"编码 {result.encoding_label}")
        self._status_total.setText(f"{format_count(result.entry_count)} 条")
        self._status_time.setText(f"解析 {result.duration:.2f} s")
        return warnings

    # ------------------------------------------------------------------
    # 筛选与树
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._clear_action.setVisible(bool(text))
        if self._suppress_search:
            return
        if not self._validate_search():
            return
        self._schedule_refresh()

    def _on_search_mode_changed(self, _checked: bool) -> None:
        if not self._validate_search():
            return
        self._schedule_refresh(immediate=True)

    def _validate_search(self) -> bool:
        if not self._regex_toggle.isChecked():
            self._set_search_invalid(False)
            return True
        try:
            build_pattern(
                Query(
                    text=self.search.text(),
                    use_regex=True,
                    case_sensitive=self._case_toggle.isChecked(),
                )
            )
        except SearchError as exc:
            self._set_search_invalid(True, f"正则表达式无效：{exc}")
            self._status_msg.setText(f"正则表达式无效：{exc}")
            return False
        self._set_search_invalid(False)
        return True

    def _set_search_invalid(self, invalid: bool, message: str = "") -> None:
        self.search.setProperty("invalid", bool(invalid))
        self.search.setToolTip(
            message if invalid else "支持关键词搜索，Ctrl+F 聚焦"
        )
        self.search.style().unpolish(self.search)
        self.search.style().polish(self.search)

    def _schedule_refresh(self, immediate: bool = False) -> None:
        if immediate:
            self._filter_timer.stop()
            self._refresh_now()
        else:
            self._filter_timer.start()

    def _on_levels_changed(self, levels) -> None:
        self._active_levels = set(levels)
        self._refresh_now()

    def open_time_filter(self) -> None:
        source = self._base_result or self._result
        if source is None:
            self.show_toast("请先加载日志文件", "info")
            return
        file_start = source.source_first_timestamp or source.first_timestamp
        file_end = source.source_last_timestamp or source.last_timestamp
        if file_start is None or file_end is None:
            self.show_toast("当前日志没有可用时间戳，无法按时间筛选", "error")
            return
        current_start = (
            self._time_start
            or (self._result.first_timestamp if self._result else None)
            or file_start
        )
        current_end = (
            self._time_end
            or (self._result.last_timestamp if self._result else None)
            or file_end
        )
        dialog = TimeRangeDialog(
            self,
            since=current_start,
            until=current_end,
            file_start=file_start,
            file_end=file_end,
            file_truncated=source.truncated,
        )
        dialog.setWindowIcon(app_icon())
        if dialog.exec_() != QDialog.Accepted:
            return
        if dialog.cleared:
            self.apply_time_range(None, None)
        else:
            self.apply_time_range(dialog.since, dialog.until)

    @staticmethod
    def _range_covered(
        result: Optional[ParseResult],
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> bool:
        if result is None:
            return False
        first = result.first_timestamp
        last = result.last_timestamp
        if first is None or last is None:
            return False
        source_first = result.source_first_timestamp or first
        source_last = result.source_last_timestamp or last
        lower = start if start is not None else source_first
        upper = end if end is not None else source_last
        if lower > source_last or upper < source_first:
            return True
        lower = max(lower, source_first)
        upper = min(upper, source_last)
        return lower >= first and upper <= last

    @staticmethod
    def _range_note(start: Optional[datetime], end: Optional[datetime]) -> str:
        parts: list[str] = []
        if start is not None:
            parts.append(f"{start:%Y-%m-%d %H:%M:%S} 起")
        if end is not None:
            parts.append(f"{end:%Y-%m-%d %H:%M:%S} 止")
        text = "，".join(parts) if parts else "指定范围"
        return f"当前仅加载 {text} 的日志；清除时间筛选可恢复最近 300,000 条"

    def _switch_source_result(
        self, result: ParseResult, *, note: str = ""
    ) -> None:
        self._result = result
        self._close_context_dialog()
        self._summary = None
        self._selected_entry = None
        self.detail_panel.clear()
        self.tree.clear()
        self._update_source_metadata(result, note=note)
        self._refresh_now()

    def _revert_range_filter(self) -> bool:
        previous = self._range_previous
        if previous is None:
            return False
        self._range_previous = None
        self._time_start, self._time_end = previous
        self.level_filter.set_time_filter(self._time_start, self._time_end)
        return True

    def _load_time_range(
        self,
        start: Optional[datetime],
        end: Optional[datetime],
        previous: tuple[Optional[datetime], Optional[datetime]],
    ) -> None:
        base = self._base_result
        if base is None:
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        self._filter_timer.stop()
        self._load_token += 1
        token = self._load_token
        self._range_previous = previous
        self._loading_state.begin(f"{base.path.name} · 指定时间范围")
        self._stack.setCurrentWidget(self._loading_state)
        self._export_btn.setEnabled(False)
        self._status_msg.setText("正在读取所选时间范围…")

        worker = ParseWorker(
            base.path,
            self,
            time_start=start,
            time_end=end,
        )
        worker.progressed.connect(
            lambda read, total, entries, t=token: self._on_progress(
                t, read, total, entries
            )
        )
        worker.succeeded.connect(
            lambda result, t=token, s=start, e=end: self._on_time_range_loaded(
                t, result, s, e
            )
        )
        worker.failed.connect(lambda message, t=token: self._on_load_failed(t, message))
        worker.cancelled.connect(lambda t=token: self._on_load_cancelled(t))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._workers.add(worker)
        self._worker = worker
        worker.start()

    def _on_time_range_loaded(
        self,
        token: int,
        result: ParseResult,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> None:
        if token != self._load_token:
            return
        self._range_previous = None
        if (start, end) != (self._time_start, self._time_end):
            self.apply_time_range(self._time_start, self._time_end)
            return
        self._range_result = result
        self._range_bounds = (start, end)
        self._switch_source_result(result, note=self._range_note(start, end))
        if result.entries:
            self.show_toast(
                f"已加载所选时间范围的 {format_count(result.entry_count)} 条日志",
                "success",
            )
        else:
            self.show_toast("所选时间范围内没有日志", "warning")

    def apply_time_range(
        self,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> None:
        previous = (self._time_start, self._time_end)
        self._time_start = since
        self._time_end = until
        self.level_filter.set_time_filter(since, until)
        if self._result is None:
            self._refresh_now()
            return
        base = self._base_result or self._result
        if since is None and until is None:
            if self._result is not base:
                self._switch_source_result(base)
            else:
                self._refresh_now()
            return
        if self._range_covered(base, since, until):
            if self._result is not base:
                self._switch_source_result(base)
            else:
                self._refresh_now()
            return
        if self._range_result is not None and self._range_bounds == (since, until):
            if self._result is not self._range_result:
                self._switch_source_result(
                    self._range_result,
                    note=self._range_note(*self._range_bounds),
                )
            else:
                self._refresh_now()
            return
        self._load_time_range(since, until, previous)

    def _on_module_cleared(self) -> None:
        self._module_filter = None
        self.level_filter.set_module_filter(None)
        self._refresh_now()

    def _on_module_clicked(self, module: str) -> None:
        if self._module_filter == module:
            self._module_filter = None
        else:
            self._module_filter = module
        self.level_filter.set_module_filter(self._module_filter)
        self._refresh_now()

    def reset_filters(self) -> None:
        self._filter_timer.stop()
        self._suppress_search = True
        self.search.clear()
        self._suppress_search = False
        self._clear_action.setVisible(False)
        self._set_search_invalid(False)
        self._active_levels = set(LEVELS)
        self._module_filter = None
        self.level_filter.set_module_filter(None)
        self._time_start = None
        self._time_end = None
        self.level_filter.set_time_filter(None, None)
        self.level_filter.set_file_time_span("")
        if self._result is not None:
            self.level_filter.set_counts(
                self._result.level_counts, set(LEVELS)
            )
        else:
            self.level_filter.set_counts({}, set(LEVELS))
        self._refresh_now()

    def set_search_text(self, text: str, *, immediate: bool = False) -> None:
        self.search.setText(text)
        if immediate:
            self._refresh_now()

    def _preferred_field(self) -> Optional[str]:
        if self._summary is None or not self._summary.fields:
            return None
        categorical = [
            stat
            for stat in self._summary.fields
            if stat.unique <= 24 and stat.count >= 3
        ]
        if categorical:
            return max(categorical, key=lambda stat: stat.count).name
        return self._summary.fields[0].name

    def set_view_mode(self, mode: str) -> None:
        if mode not in ("level", "module", "time", "field"):
            return
        if mode == self._view_mode:
            self._view_buttons[mode].setChecked(True)
            return
        if mode == "field":
            if self._summary is None or not self._summary.fields:
                self._view_buttons[self._view_mode].setChecked(True)
                self.show_toast("当前筛选结果没有可用的键值字段", "info")
                return
            if self._field_name is None or self._field_name not in {
                stat.name for stat in self._summary.fields
            }:
                self._field_name = self._preferred_field()
        self._save_group_states()
        self._view_mode = mode
        self._view_buttons[mode].setChecked(True)
        self._field_bar.setVisible(mode == "field")
        if mode == "field":
            self._sync_field_combo()
        self._refresh_now()

    def _sync_field_combo(self) -> None:
        names: list[str] = []
        if self._summary is not None:
            names = [stat.name for stat in self._summary.fields]
        if self._field_name and self._field_name not in names:
            names.insert(0, self._field_name)
        if not self._field_name and names:
            self._field_name = self._preferred_field()
        self._field_combo.blockSignals(True)
        self._field_combo.clear()
        self._field_combo.addItems(names)
        if self._field_name:
            index = self._field_combo.findText(self._field_name)
            if index >= 0:
                self._field_combo.setCurrentIndex(index)
        self._field_combo.blockSignals(False)
        self._field_bar.setVisible(self._view_mode == "field" and bool(names))

    def _on_field_changed(self, text: str) -> None:
        if self._view_mode != "field" or not text or text == self._field_name:
            return
        self._field_name = text
        self._refresh_now()

    def _on_field_activated(self, field: str) -> None:
        if not field or self._summary is None:
            return
        if self._view_mode != "field":
            self._save_group_states()
            self._view_mode = "field"
            self._view_buttons["field"].setChecked(True)
        self._field_name = field
        self._field_bar.setVisible(True)
        self._sync_field_combo()
        self._refresh_now()

    def _refresh_now(self) -> None:
        self._filter_timer.stop()
        if self._result is None:
            return
        query = Query(
            text=self.search.text(),
            use_regex=self._regex_toggle.isChecked(),
            case_sensitive=self._case_toggle.isChecked(),
            levels=frozenset(self._active_levels),
            module=self._module_filter,
            time_start=self._time_start,
            time_end=self._time_end,
        )
        heavy = len(self._result.entries) > 20000
        if heavy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            try:
                matched = filter_entries(self._result.entries, query)
            except SearchError as exc:
                self._set_search_invalid(True, f"正则表达式无效：{exc}")
                self._status_msg.setText(f"正则表达式无效：{exc}")
                return
            self._set_search_invalid(False)
            self._query = query
            self._matched = matched
            summary = summarize(
                self._result.entries,
                matched,
                total_level_counts=self._result.level_counts,
            )
        finally:
            if heavy:
                QApplication.restoreOverrideCursor()

        self._summary = summary
        self.sidebar.update_summary(summary)
        self._update_status_labels()
        self._export_btn.setEnabled(bool(matched))
        self._sync_field_combo()

        if not matched:
            self._save_group_states()
            self.tree.clear()
            self._selected_entry = None
            self.detail_panel.clear()
            if not self._result.entries:
                if self._result is self._range_result:
                    self._show_time_range_empty_state()
                else:
                    self._show_empty_file_state()
            else:
                self._show_noresult_state()
            self._stack.setCurrentWidget(self._noresult_state)
            if self._result.entries:
                self._status_msg.setText("没有匹配的日志")
            elif self._result is self._range_result:
                self._status_msg.setText("所选时间范围内没有日志")
            else:
                self._status_msg.setText("日志文件为空")
            return

        self._rebuild_tree(matched, summary)
        self._stack.setCurrentWidget(self.tree)
        if query.has_filters:
            self._status_msg.setText(f"匹配 {format_count(len(matched))} 条日志")
        else:
            self._status_msg.setText(f"已加载 {format_count(len(matched))} 条日志")

    def _update_status_labels(self) -> None:
        if self._result is None or self._summary is None:
            return
        self._status_encoding.setText(f"编码 {self._result.encoding_label}")
        self._status_total.setText(f"{format_count(self._result.entry_count)} 条")
        self._status_matched.setText(f"匹配 {format_count(self._summary.matched)}")
        self._status_time.setText(f"解析 {self._result.duration:.2f} s")

    def _show_empty_file_state(self) -> None:
        self._noresult_mode = "open"
        file_name = self._result.path.name if self._result else "该文件"
        self._noresult_state.configure(
            "日志文件为空",
            f"{file_name} 中没有可解析的文本内容。\n请检查文件或选择其他日志。",
            "选择其他文件",
            icon_name="file",
            use_logo=False,
            primary=True,
        )

    def _show_noresult_state(self) -> None:
        self._noresult_mode = "reset"
        self._noresult_state.configure(
            "没有匹配的日志",
            "尝试调整关键词、级别、模块或时间筛选，\n或重置全部条件。",
            "重置筛选",
            icon_name="search",
            use_logo=False,
            primary=False,
        )

    def _show_time_range_empty_state(self) -> None:
        self._noresult_mode = "time"
        self._noresult_state.configure(
            "所选时间范围内没有日志",
            "该时间段内没有可显示的日志。\n可以修改时间范围，或清除时间筛选。",
            "修改时间范围",
            icon_name="search",
            use_logo=False,
            primary=False,
        )

    def _on_noresult_action(self) -> None:
        if self._noresult_mode == "open":
            self.open_dialog()
        elif self._noresult_mode == "time":
            self.open_time_filter()
        else:
            self.reset_filters()

    def _save_group_states(self) -> None:
        if self.tree.topLevelItemCount() == 0:
            return
        states: dict[str, bool] = {}
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            key = item.data(0, ROLE_GROUP_KEY)
            if key:
                states[key] = item.isExpanded()
        if states:
            self._group_state[self._tree_mode] = states

    def _default_expansions(self, groups, mode: str) -> set[str]:
        keys: set[str] = set()
        if mode == "level":
            by_level = {group.level: group for group in groups}
            budget = 4200
            for level in ("ERROR", "CRITICAL", "WARNING", "INFO", "OTHER", "DEBUG", "TRACE"):
                group = by_level.get(level)
                if group is None:
                    continue
                cost = min(len(group.entries), PER_GROUP_LIMIT)
                if keys and cost > budget:
                    break
                keys.add(group.key)
                budget -= cost
            return keys
        if mode == "module":
            budget = 2600
            for group in groups[:4]:
                cost = min(len(group.entries), PER_GROUP_LIMIT)
                if keys and cost > budget:
                    break
                keys.add(group.key)
                budget -= cost
            return keys
        if mode == "time" and groups:
            first = groups[0]
            if first.key != "time:__missing__":
                keys.add(first.key)
            return keys
        if mode == "field":
            budget = 3000
            for group in groups[:4]:
                cost = min(len(group.entries), PER_GROUP_LIMIT)
                if keys and cost > budget:
                    break
                keys.add(group.key)
                budget -= cost
        return keys

    def _rebuild_tree(self, matched, summary: Summary) -> None:
        self._save_group_states()
        mode = self._view_mode
        groups = build_groups(
            matched,
            mode,
            summary.histogram,
            field=self._field_name if mode == "field" else None,
        )
        defaults = self._default_expansions(groups, mode)
        stored = dict(self._group_state.get(mode, {}))
        total = max(1, len(matched))

        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self._tree_mode = mode
            for index, group in enumerate(groups):
                item = QTreeWidgetItem([group.title, "", "", ""])
                item.setFirstColumnSpanned(True)
                item.setData(0, ROLE_GROUP, True)
                item.setData(0, ROLE_GROUP_KEY, group.key)
                item.setData(0, ROLE_GROUP_ENTRIES, group.entries)
                item.setData(0, ROLE_GROUP_SHARE, len(group.entries) / total)
                item.setData(0, ROLE_GROUP_HINT, group.hint)
                item.setData(0, ROLE_GROUP_LEVEL, group.level)
                item.setToolTip(0, group.title)
                item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ShowIndicator
                    if group.entries
                    else QTreeWidgetItem.DontShowIndicator
                )
                self.tree.addTopLevelItem(item)
                self.tree.setFirstColumnSpanned(
                    self.tree.indexOfTopLevelItem(item), QModelIndex(), True
                )
                expanded = stored.get(group.key, group.key in defaults)
                item.setExpanded(expanded)
            self.detail_panel.clear()
            self._selected_entry = None
        finally:
            self.tree.setUpdatesEnabled(True)
        self.tree.scrollToTop()
        self.tree.verticalScrollBar().setValue(0)
        self.tree.viewport().update()
        self.tree.schedule_layout_refresh()
        self._apply_responsive()

    def _create_entry_item(self, entry) -> QTreeWidgetItem:
        return build_entry_item(entry, self._query)

    @staticmethod
    def _notice_text(total: int, shown: int) -> str:
        chunk = min(total - shown, PER_GROUP_LIMIT)
        return (
            f"共 {format_count(total)} 条 · 已显示最近 {format_count(shown)} 条（末尾为最新） · "
            f"点击加载更早的 {format_count(chunk)} 条"
        )

    def _populate_group(self, item: QTreeWidgetItem) -> None:
        if item is None or not item.data(0, ROLE_GROUP):
            return
        if item.data(0, ROLE_GROUP_POPULATED):
            return
        entries = item.data(0, ROLE_GROUP_ENTRIES) or []
        if not entries:
            return
        total = len(entries)
        shown = min(total, PER_GROUP_LIMIT)
        children = [
            self._create_entry_item(entry)
            for entry in entries[total - shown:]
        ]
        self.tree.setUpdatesEnabled(False)
        try:
            if total > shown:
                notice = QTreeWidgetItem(["", "", "", ""])
                notice.setFlags(Qt.ItemIsEnabled)
                notice.setData(0, ROLE_NOTICE, self._notice_text(total, shown))
                notice.setToolTip(0, "点击加载更早的日志")
                item.addChild(notice)
                self.tree.setFirstColumnSpanned(
                    item.indexOfChild(notice), self.tree.indexFromItem(item), True
                )
            item.addChildren(children)
            item.setData(0, ROLE_GROUP_SHOWN, shown)
            item.setData(0, ROLE_GROUP_POPULATED, True)
        finally:
            self.tree.setUpdatesEnabled(True)
            self.tree.schedule_layout_refresh()

    def _load_earlier(self, item: QTreeWidgetItem) -> None:
        entries = item.data(0, ROLE_GROUP_ENTRIES) or []
        total = len(entries)
        shown = int(item.data(0, ROLE_GROUP_SHOWN) or 0)
        if shown >= total:
            return
        chunk = min(total - shown, PER_GROUP_LIMIT)
        start = total - shown - chunk
        children = [
            self._create_entry_item(entry)
            for entry in entries[start:start + chunk]
        ]
        notice = item.child(0) if item.childCount() > 0 else None
        if notice is not None and not notice.data(0, ROLE_NOTICE):
            notice = None
        base = 1 if notice is not None else 0
        self.tree.setUpdatesEnabled(False)
        try:
            item.insertChildren(base, children)
            shown += chunk
            item.setData(0, ROLE_GROUP_SHOWN, shown)
            if shown >= total:
                if notice is not None:
                    item.removeChild(notice)
            elif notice is not None:
                notice.setData(0, ROLE_NOTICE, self._notice_text(total, shown))
        finally:
            self.tree.setUpdatesEnabled(True)
            self.tree.schedule_layout_refresh()

    def _on_tree_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item is None:
            return
        if item.data(0, ROLE_NOTICE):
            if item.parent() is not None:
                self._load_earlier(item.parent())
            return
        if item.data(0, ROLE_GROUP):
            item.setExpanded(not item.isExpanded())
            self.tree.schedule_layout_refresh()

    def _on_selection_changed(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        if item.data(0, ROLE_GROUP) or item.data(0, ROLE_NOTICE):
            self._selected_entry = None
            self.detail_panel.clear()
            return
        entry = item.data(0, ROLE_ENTRY)
        if entry is None:
            return
        self._selected_entry = entry
        if self.detail_panel.isVisible():
            self.detail_panel.set_entry(entry, self._query)

    def _on_tree_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item is None or item.data(0, ROLE_GROUP):
            return
        entry = item.data(0, ROLE_ENTRY)
        if entry is None:
            return
        self._selected_entry = entry
        self._ensure_detail_visible()
        self._show_time_context(entry)

    def _show_time_context(self, entry) -> None:
        """双击日志后，弹出该条日志前后 30 秒的平铺日志窗口。"""

        if entry.timestamp is None:
            self.show_toast("该条日志没有时间戳，无法显示前后日志", "info")
            return
        if self._result is None:
            return
        self._close_context_dialog()
        dialog = ContextDialog(
            self._result.entries,
            entry,
            seconds=CONTEXT_WINDOW_SECONDS,
            parent=self,
        )
        dialog.destroyed.connect(self._on_context_dialog_destroyed)
        self._context_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_context_dialog(self) -> None:
        dialog = self._context_dialog
        self._context_dialog = None
        if dialog is not None and not sip.isdeleted(dialog):
            dialog.close()

    def _on_context_dialog_destroyed(self, _obj=None) -> None:
        dialog = self._context_dialog
        if dialog is not None and sip.isdeleted(dialog):
            self._context_dialog = None

    def expand_all(self) -> None:
        if self.tree.topLevelItemCount() == 0:
            return
        budget = EXPAND_BUDGET
        skipped = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            entries = item.data(0, ROLE_GROUP_ENTRIES) or []
            cost = min(len(entries), PER_GROUP_LIMIT)
            if budget - cost < 0:
                skipped += 1
                continue
            budget -= cost
            item.setExpanded(True)
        self.tree.viewport().update()
        self.tree.schedule_layout_refresh()
        if skipped:
            self.show_toast(
                f"已达渲染上限，仍有 {skipped} 个分组未展开；导出不受影响",
                "info",
            )

    def collapse_all(self) -> None:
        self.tree.collapseAll()
        self.tree.schedule_layout_refresh()

    # ------------------------------------------------------------------
    # 右键菜单与复制
    # ------------------------------------------------------------------

    def _show_tree_menu(self, point: QPoint) -> None:
        item = self.tree.itemAt(point)
        menu = QMenu(self)
        entry = None
        if item is not None and not item.data(0, ROLE_GROUP) and not item.data(0, ROLE_NOTICE):
            entry = item.data(0, ROLE_ENTRY)
        if entry is not None:
            view_action = menu.addAction(icon("search", MUTED, 15), "在详情中查看")
            view_action.triggered.connect(
                lambda: self._show_entry_in_detail(entry)
            )
            copy_raw = menu.addAction(icon("copy", MUTED, 15), "复制原始日志")
            copy_raw.triggered.connect(lambda: self._copy_text(entry.raw, "已复制原始日志"))
            copy_msg = menu.addAction(icon("copy", MUTED, 15), "复制消息")
            copy_msg.triggered.connect(lambda: self._copy_text(entry.message, "已复制日志消息"))
            menu.addSeparator()
        if item is not None and item.data(0, ROLE_GROUP):
            if item.isExpanded():
                toggle = menu.addAction(icon("collapse", MUTED, 15), "折叠该分组")
                toggle.triggered.connect(lambda: item.setExpanded(False))
            else:
                toggle = menu.addAction(icon("expand", MUTED, 15), "展开该分组")
                toggle.triggered.connect(lambda: item.setExpanded(True))
            menu.addAction("全部展开", self.expand_all)
            menu.addAction("全部折叠", self.collapse_all)
            menu.addSeparator()
        export_action = menu.addAction(icon("export", MUTED, 15), "导出当前筛选结果…")
        export_action.setEnabled(bool(self._matched))
        export_action.triggered.connect(self.export_dialog)
        reset_action = menu.addAction(icon("reset", MUTED, 15), "重置搜索与筛选")
        reset_action.triggered.connect(self.reset_filters)
        menu.exec_(self.tree.viewport().mapToGlobal(point))

    def _show_entry_in_detail(self, entry) -> None:
        self._selected_entry = entry
        self._ensure_detail_visible()
        self.detail_panel.set_entry(entry, self._query)

    def _copy_text(self, text: str, message: str) -> None:
        QApplication.clipboard().setText(text)
        self.show_toast(message, "success")

    def copy_selected_raw(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        entry = item.data(0, ROLE_ENTRY)
        if entry is not None:
            self._copy_text(entry.raw, "已复制原始日志")

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def export_dialog(self) -> None:
        if not self._matched:
            self.show_toast("没有可导出的日志", "warning")
            return
        stem = self._result.path.stem if self._result is not None else "loglens"
        default = Path(self._last_dir) / f"{stem}_filtered.csv"
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出筛选结果",
            str(default),
            "CSV 文件 (*.csv);;JSON Lines (*.jsonl);;JSON 文件 (*.json);;文本日志 (*.txt *.log)",
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            suffix = {
                "CSV 文件 (*.csv)": ".csv",
                "JSON Lines (*.jsonl)": ".jsonl",
                "JSON 文件 (*.json)": ".json",
                "文本日志 (*.txt *.log)": ".txt",
            }.get(selected, ".csv")
            target = target.with_suffix(suffix)
        self._last_dir = str(target.parent)
        self.export_to(target)

    def export_to(self, path: str | Path) -> int:
        if not self._matched:
            self.show_toast("没有可导出的日志", "warning")
            return 0
        try:
            count = export_entries(self._matched, path)
        except OSError as exc:
            self.show_toast(f"导出失败：{exc}", "error")
            QMessageBox.warning(self, "导出失败", str(exc))
            return 0
        self.show_toast(
            f"已导出 {format_count(count)} 条日志到 {Path(path).name}", "success"
        )
        self._status_msg.setText(f"已导出 {format_count(count)} 条日志")
        return count

    # ------------------------------------------------------------------
    # 帮助
    # ------------------------------------------------------------------

    def show_toast(self, message: str, kind: str = "success") -> None:
        self._toast.show_message(message, kind)

    def show_help(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("HelpDialog")
        dialog.setWindowTitle("使用说明 · LogLens")
        dialog.setWindowIcon(app_icon())
        dialog.resize(680, 640)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        title = QLabel("LogLens 使用说明")
        title.setStyleSheet("font-size:17px;font-weight:700;color:#0F172A;")
        layout.addWidget(title)
        browser = QTextBrowser()
        browser.setObjectName("HelpText")
        browser.setOpenExternalLinks(False)
        browser.setHtml(_help_html())
        layout.addWidget(browser, 1)
        close = QPushButton("关闭")
        close.setObjectName("Primary")
        close.setFixedHeight(34)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec_()


def _help_html() -> str:
    html = """
    <html><head><style>
    body { font-family: "Microsoft YaHei UI", "Segoe UI"; color:#334155; font-size:12px; line-height:1.65; }
    h3 { color:#0F172A; font-size:13px; margin:14px 0 6px 0; }
    code { background:#F1F5F9; color:#1D4ED8; padding:1px 4px; border-radius:3px; }
    table { border-collapse: collapse; width:100%; margin-top:4px; }
    td { border-bottom:1px solid #EEF2F7; padding:5px 4px; }
    td.k { width:150px; color:#64748B; }
    .muted { color:#94A3B8; font-size:11px; }
    .tip { background:#EFF6FF; border-left:3px solid #2563EB; padding:8px 10px; border-radius:4px; color:#1E40AF; }
    </style></head><body>
    <p class="muted">一个轻量、现代的桌面日志分析工具。无需上传，所有解析均在本机完成。</p>

    <h3>1. 导入日志</h3>
    <p>把任意文本日志文件拖到窗口任意位置，出现深色遮罩后松开即可；也可以点击右上角
    <b>打开日志</b> 或按 <code>Ctrl+O</code>。打开对话框默认从启动目录（当前工作目录或
    程序所在目录）开始，打开过文件后会记住该文件所在目录。工具会自动检测编码
    （UTF-8 / UTF-8 BOM / UTF-16 / GB18030 / Windows-1252 等），大文件在后台解析并显示进度。</p>
    <p class="tip">如果日志被 E-SafeNet 等透明加密软件保护，程序会提示加密头；
    请将 LogLens.exe 加入白名单，或双击 run_loglens.pyw（受信任的 Python）运行。</p>

    <h3>2. 分类与统计</h3>
    <p>默认按 <b>级别</b> 分组：TRACE、DEBUG、INFO、WARNING、ERROR、CRITICAL、OTHER，
    每个分组有独立颜色、数量与占比。工具栏右侧可切换 <b>按模块</b>、<b>按时间</b>、
    <b>按字段</b> 分组；按字段模式下可在树顶选择用于分组的键值字段，左侧“关键字段”
    中双击任意字段也能直接切换。</p>
    <p>点击分组标题即可折叠/展开；单组默认渲染最近 1000 条，点击列表顶部的提示
    可继续加载更早记录，避免超大日志卡顿，分组计数与导出仍包含全部匹配记录。</p>
    <p>左侧统计面板展示级别占比环图、时间趋势、高频模块和关键字段；
    点击高频模块可直接筛选该模块。</p>

    <h3>3. 搜索与筛选</h3>
    <p>顶部搜索框支持普通关键词与正则表达式（点击 <code>.*</code> 切换），
    <code>Aa</code> 控制大小写敏感。命中内容会在列表和详情面板中高亮。
    级别标签可独立开关，“全部”用于恢复所有级别。</p>
    <p>点击筛选栏的 <b>“时间”</b> 打开时间范围弹窗，分别选择起始和结束日期、时间；
    日期可用日历选择，时间可直接输入或用上下箭头调整。应用后只显示该区间内的日志，
    结束秒内的毫秒日志也会包含；无时间戳的日志会被排除。如果所选范围早于最近保留的
    300,000 条，会自动按该时间段重新读取文件。关键词、级别、模块与时间条件
    会同时生效，<code>Ctrl+L</code> 可一键重置。</p>
    <p>示例：<code>timeout|refused</code>、<code>battery=\\d+</code>、
    <code>^.*ERROR.*$</code>。</p>

    <h3>4. 查看详情</h3>
    <p>单击日志查看原始内容、完整堆栈与解析出的键值字段；双击会弹出独立的
    <b>上下文窗口</b>：默认显示该条日志前后 30 秒的记录，右上角“前后跨度”可在
    1–3600 秒之间调整。窗口只按时间正序平铺，不按级别分组；每条日志展示完整
    原始内容（多行堆栈、矩阵原样显示），目标日志以黄色高亮并自动滚动到中间；
    点击右上角“文本”可切换为直接展示原始日志文本；顶部显示条数与时间范围，
    底部可“复制全部”。上下文取自全部已加载日志，不受当前级别 / 模块 / 搜索筛选影响。
    无时间戳的日志会提示无法定位。</p>
    <p>解析出的矩阵字段按 n×n 展开显示，向量与 double* 序列会自动换行。
    详情面板右上角按钮可复制原始日志，列表右键菜单也提供复制与快捷操作。</p>

    <h3>5. 导出</h3>
    <p>按 <code>Ctrl+E</code> 或点击 <b>导出</b>，可将当前筛选结果保存为
    CSV（含 BOM，便于 Excel 打开）、JSON、JSON Lines 或原始文本。
    导出包含全部匹配记录，不受列表渲染上限影响。</p>

    <h3>6. 快捷键</h3>
    <table>
      <tr><td class="k">Ctrl + O</td><td>打开日志文件</td></tr>
      <tr><td class="k">Ctrl + E</td><td>导出当前筛选结果</td></tr>
      <tr><td class="k">Ctrl + F</td><td>聚焦搜索框</td></tr>
      <tr><td class="k">Ctrl + L</td><td>重置搜索与筛选</td></tr>
      <tr><td class="k">Ctrl + Shift + E</td><td>全部展开</td></tr>
      <tr><td class="k">Ctrl + Shift + W</td><td>全部折叠</td></tr>
      <tr><td class="k">F1</td><td>打开本说明</td></tr>
    </table>

    <h3>7. 支持格式</h3>
    <p>常见时间戳 + 级别格式、Python logging、log4j / logback、Spring Boot、
    syslog、glog、Android Logcat、JSON Lines；无法识别结构的纯文本会按关键字
    （error / failed / warn 等）推断级别，并归入 OTHER 或对应级别。</p>
    <p>项目 <code>main.log</code> 的 <code>[时间][级别] [Class::method]</code> 格式与
    <code>+---+ / | # | joint | ... |</code> ASCII 表格也已支持：表格行会继承上一条日志的
    时间、级别与模块，并解析出 joint、mode、fb.q 等字段，可在“按字段”视图中按
    joint 分组查看。</p>
    <p>项目 <code>LOUT</code> 的 <code>[时间] [codeit] ...</code>、
    <code>[warn][/path/a.cpp:268] ...</code>、<code>[instrument][info] ...</code>
    方括号标签格式同样支持：标签作为模块，第二个方括号中的级别或源码位置会被识别，
    缺少时间戳的后续行会沿用上一条日志的时间。</p>
    <p>codeit 的 <code>server parse cmd 8115 : {A||B --k=v||...}</code> 会按
    <code>||</code> 拆分 model（索引从 0 开始），生成 <code>cmd_id</code>、
    <code>model_count</code>、<code>m0.cmd</code>、<code>m3.mode_id</code> 等字段；
    <code>--vel={0,0.02,0,0,0,0}</code> 这类数组参数会保留为逗号分隔文本。</p>
    <p>同时支持 <code>tclog/formatters.hpp</code> 中的 Eigen 矩阵 / 向量、Eigen Transform、
    std::vector、Span 输出：单行 <code>q=0.1, 0.2, 0.3</code>、<code>param:goal=0,0,0</code>
    以及 key 行后跟多行数值的 4x4 矩阵都会提取为字段；多行数值自动归并为同一条日志。</p>

    <h3>8. 大文件保护</h3>
    <p>超过 100 MB 的文件会在加载前确认。较大的日志会直接从文件末尾定位并解析
    最近 300,000 条（不再从文件头读完整份文件），同时额外读取文件头尾以得到
    <b>整个文件的完整时间跨度</b>，时间筛选仍可定位到任意时间段；如果选择的
    范围早于已加载窗口，会自动按该时间段重新读取文件。清除时间筛选后恢复最近
    300,000 条。单条日志超过 128 KB 会截断堆栈。界面始终保留完整筛选与导出能力。</p>

    <p class="muted">LogLens v{{VERSION}} · PyQt5 · 本地离线运行</p>
    </body></html>
    """
    return html.replace("{{VERSION}}", __version__)
