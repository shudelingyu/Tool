"""PoseView 主窗口。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import app_icon, dot_icon, icon, logo_pixmap, primary_icon
from .math3d import (
    MatrixParseError,
    Pose,
    format_number,
    parse_poses,
    rotation_angle_between,
)
from .relative_dialog import RelativePoseDialog
from .robot_dialog import RobotDialog
from .scene import POSE_COLORS, PoseScene, RobotSkeleton, SceneFrame, ScenePose
from .theme import DANGER, MUTED, SUCCESS, mono_font
from .urdf import UrdfError, UrdfRobot, load_urdf
from .widgets import PoseValuePanel

SAMPLE_MATRICES = """1 0 0 0
0 1 0 0
0 0 1 0
0 0 0 1

0.707107 -0.707107 0 1.2
0.707107 0.707107 0 0
0 0 1 0.35
0 0 0 1

0 1 0 2.4
-1 0 0 0.9
0 0 1 0.85
0 0 0 1

0.5 -0.866025 0 3.2
0.866025 0.5 0 1.7
0 0 1 1.5
0 0 0 1"""

DEFAULT_STATUS = "左键旋转 · 右键平移 · 滚轮缩放 · 双击复位"

QUAT_SAMPLE = """0 0 0   1 0 0 0

1.2 0 0.35   0.92388 0 0 0.382683

2.4 0.9 0.85   0.707107 0 0 0.707107

3.2 1.7 1.5   0.866025 0 0 0.5"""

EULER_SAMPLE = """0 0 0   0 0 0

1.2 0 0.35   0 0 45

2.4 0.9 0.85   0 0 90

3.2 1.7 1.5   0 0 60"""

INPUT_MODES = (
    ("matrix", "齐次矩阵"),
    ("quat", "位置 + 四元数"),
    ("euler", "位置 + 欧拉角"),
)

SAMPLES = {
    "matrix": SAMPLE_MATRICES,
    "quat": QUAT_SAMPLE,
    "euler": EULER_SAMPLE,
}

MODE_HINTS = {
    "matrix": "支持 3x3 / 3x4 / 4x4；空行或 --- 分隔多个矩阵",
    "quat": "每帧 7 个数：x y z qw qx qy qz；空行或 --- 分隔多帧",
    "euler": "每帧 6 个数：x y z roll pitch yaw（度）；空行或 --- 分隔多帧",
}

PLACEHOLDERS = {
    "matrix": (
        "粘贴 3x3 / 3x4 / 4x4 矩阵：\n"
        "1  0  0  0.5\n"
        "0  1  0  0\n"
        "0  0  1  0\n"
        "0  0  0  1"
    ),
    "quat": (
        "粘贴位置 + 四元数，每帧 7 个数：\n"
        "x y z qw qx qy qz\n"
        "0 0 0   1 0 0 0"
    ),
    "euler": (
        "粘贴位置 + 欧拉角，每帧 6 个数：\n"
        "x y z roll pitch yaw\n"
        "0 0 0   0 0 45"
    ),
}


@dataclass
class _Entry:
    name: str
    color: str
    pose: Pose
    visible: bool = True


def _translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    return (matrix[0][3], matrix[1][3], matrix[2][3])


def _rotation(matrix: list[list[float]]) -> list[list[float]]:
    return [row[:3] for row in matrix[:3]]


def _distance(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return math.sqrt(
        (first[0] - second[0]) ** 2
        + (first[1] - second[1]) ** 2
        + (first[2] - second[2]) ** 2
    )


class PoseViewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[_Entry] = []
        self._mode = "matrix"
        self._default_hint = MODE_HINTS["matrix"]
        self._robot: UrdfRobot | None = None
        self._joint_values: dict[str, float] = {}
        self._ee_link = ""
        self._robot_target: list[list[float]] | None = None
        self._robot_dialog: RobotDialog | None = None
        self._build_ui()
        self._build_shortcuts()
        self._build_status_bar()

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._reset_hint)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status)

        self._initial_fit_timer = QTimer(self)
        self._initial_fit_timer.setSingleShot(True)
        self._initial_fit_timer.timeout.connect(self._scene.fit_view)
        self._initial_fit_timer.start(60)

        self._load_demo()

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("PoseView · 位姿矩阵可视化")
        self.setWindowIcon(app_icon())
        self.resize(1360, 880)
        self.setMinimumSize(1120, 740)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_view())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([344, 970])

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(14, 14, 14, 12)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(splitter)
        outer.addWidget(wrapper, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(66)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(38))
        logo.setFixedSize(38, 38)
        layout.addWidget(logo)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("PoseView")
        title.setObjectName("AppTitle")
        subtitle = QLabel("位姿矩阵 · 三维可视化")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        badge = QLabel("矩阵 · 四元数 · 欧拉角")
        badge.setObjectName("Badge")
        layout.addWidget(badge)

        relative_button = QPushButton("相对位姿")
        relative_button.setObjectName("Ghost")
        relative_button.setIcon(icon("swap", "#475569", 15))
        relative_button.setCursor(Qt.PointingHandCursor)
        relative_button.setToolTip("计算两个坐标系之间的相对位姿")
        relative_button.clicked.connect(self._show_relative_dialog)
        layout.addWidget(relative_button)

        help_button = QPushButton("使用说明")
        help_button.setObjectName("Ghost")
        help_button.setIcon(icon("help", "#475569", 15))
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self._show_help)
        layout.addWidget(help_button)
        return header

    def _build_left(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(430)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        input_card = QFrame()
        input_card.setObjectName("Card")
        card_layout = QVBoxLayout(input_card)
        card_layout.setContentsMargins(14, 13, 14, 14)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("位姿输入")
        title.setObjectName("SectionTitle")
        hint = QLabel("统一转为 4x4 解算")
        hint.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
        card_layout.addLayout(head)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QToolButton] = {}
        for key, label in INPUT_MODES:
            button = QToolButton()
            button.setObjectName("ModeTab")
            button.setText(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, name=key: self._set_mode(name)
            )
            self._mode_group.addButton(button)
            self._mode_buttons[key] = button
            mode_row.addWidget(button, 1)
        self._mode_buttons["matrix"].setChecked(True)
        card_layout.addLayout(mode_row)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MatrixEditor")
        self._editor.setFont(mono_font(11.5))
        self._editor.setFixedHeight(148)
        self._editor.setTabChangesFocus(True)
        self._editor.setPlaceholderText(PLACEHOLDERS["matrix"])
        card_layout.addWidget(self._editor)

        self._parse_hint = QLabel(self._default_hint)
        self._parse_hint.setObjectName("CardHint")
        self._parse_hint.setWordWrap(True)
        card_layout.addWidget(self._parse_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_button = QPushButton("添加位姿")
        add_button.setObjectName("Primary")
        add_button.setIcon(primary_icon("plus", 15))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.clicked.connect(self._add_from_editor)
        clear_input = QPushButton("清空输入")
        clear_input.setObjectName("Ghost")
        clear_input.setIcon(icon("clear", "#475569", 15))
        clear_input.setCursor(Qt.PointingHandCursor)
        clear_input.clicked.connect(self._clear_editor)
        buttons.addWidget(add_button, 1)
        buttons.addWidget(clear_input)
        card_layout.addLayout(buttons)

        layout.addWidget(input_card)

        list_card = QFrame()
        list_card.setObjectName("Card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(14, 13, 14, 14)
        list_layout.setSpacing(8)

        list_head = QHBoxLayout()
        list_head.setSpacing(8)
        list_title = QLabel("位姿列表")
        list_title.setObjectName("SectionTitle")
        self._count_badge = QLabel("0 帧")
        self._count_badge.setObjectName("CountBadge")
        list_head.addWidget(list_title)
        list_head.addStretch(1)
        list_head.addWidget(self._count_badge)
        list_layout.addLayout(list_head)

        self._list = QListWidget()
        self._list.setObjectName("PoseList")
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        list_layout.addWidget(self._list, 1)

        list_buttons = QHBoxLayout()
        list_buttons.setSpacing(8)
        delete_button = QPushButton("删除选中")
        delete_button.setObjectName("Ghost")
        delete_button.setIcon(icon("trash", "#475569", 15))
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.clicked.connect(self._delete_selected)
        clear_button = QPushButton("清空列表")
        clear_button.setObjectName("Ghost")
        clear_button.setIcon(icon("clear", "#475569", 15))
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self._clear_all)
        list_buttons.addWidget(delete_button, 1)
        list_buttons.addWidget(clear_button, 1)
        list_layout.addLayout(list_buttons)

        layout.addWidget(list_card, 1)

        values_card = QFrame()
        values_card.setObjectName("Card")
        values_layout = QVBoxLayout(values_card)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(0)
        self._value_panel = PoseValuePanel()
        values_layout.addWidget(self._value_panel)
        layout.addWidget(values_card)

        return panel

    def _build_view(self) -> QFrame:
        self._scene = PoseScene()
        self._scene.pose_clicked.connect(self._on_scene_clicked)

        card = QFrame()
        card.setObjectName("ViewCard")
        card.setMinimumWidth(460)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("ViewBar")
        bar.setFixedHeight(44)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 6, 10, 6)
        bar_layout.setSpacing(4)

        title = QLabel("三维视图")
        title.setObjectName("ViewTitle")
        bar_layout.addWidget(title)
        bar_layout.addStretch(1)

        bar_layout.addWidget(self._view_button("重置", "reset", self._scene.reset_view, tooltip="恢复默认观察角度"))
        bar_layout.addWidget(self._view_button("适配", "fit", self._scene.fit_view, tooltip="缩放至全部可见几何"))
        self._pose_toggle = self._view_button(
            "位姿", "axis", self._scene.set_show_poses,
            checkable=True, checked=True, tooltip="显示 / 隐藏位姿列表中的坐标轴",
        )
        bar_layout.addWidget(self._pose_toggle)
        bar_layout.addWidget(
            self._view_button(
                "网格", "grid", self._scene.set_show_grid,
                checkable=True, checked=True, tooltip="显示 / 隐藏地面网格",
            )
        )
        bar_layout.addWidget(
            self._view_button(
                "轨迹", "path", self._scene.set_show_path,
                checkable=True, checked=True, tooltip="按列表顺序连接可见位姿",
            )
        )
        bar_layout.addWidget(
            self._view_button(
                "标签", "tag", self._scene.set_show_labels,
                checkable=True, checked=True, tooltip="显示 / 隐藏位姿名称",
            )
        )
        bar_layout.addWidget(
            self._view_button(
                "URDF", "file", self._load_urdf,
                tooltip="加载 URDF 机器人，显示关节骨架",
            )
        )
        self._robot_button = self._view_button(
            "关节", "robot", self._show_robot_dialog,
            tooltip="打开关节控制与 IK 校验（需先加载 URDF）",
        )
        self._robot_button.setEnabled(False)
        bar_layout.addWidget(self._robot_button)

        layout.addWidget(bar)
        layout.addWidget(self._scene, 1)
        return card

    def _view_button(
        self,
        text: str,
        icon_name: str,
        slot=None,
        *,
        checkable: bool = False,
        checked: bool = False,
        tooltip: str = "",
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ViewTool")
        button.setText(text)
        button.setIcon(icon(icon_name, "#CBD5E1", 15))
        button.setIconSize(QSize(15, 15))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setCursor(Qt.PointingHandCursor)
        button.setCheckable(checkable)
        button.setChecked(checked)
        if tooltip:
            button.setToolTip(tooltip)
        if slot is not None:
            if checkable:
                button.toggled.connect(slot)
            else:
                button.clicked.connect(slot)
        return button

    def _build_shortcuts(self) -> None:
        add_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        add_shortcut.activated.connect(self._add_from_editor)
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._show_help)
        delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self._list)
        delete_shortcut.setContext(Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_selected)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self._status_hint = QLabel(DEFAULT_STATUS)
        self._counts = QLabel("共 0 帧 · 显示 0 帧")
        status.addWidget(self._status_hint, 1)
        status.addPermanentWidget(self._counts)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def _load_demo(self) -> None:
        self._editor.setPlainText(SAMPLE_MATRICES)
        try:
            poses = parse_poses(SAMPLE_MATRICES)
        except MatrixParseError:
            return
        self._append_poses(poses)
        self._flash_status("已加载示例位姿，可直接替换左侧矩阵后添加")

    def _append_poses(self, poses: list[Pose]) -> None:
        start = len(self._entries)
        for offset, pose in enumerate(poses):
            index = start + offset
            self._entries.append(
                _Entry(
                    name=f"Pose {index + 1}",
                    color=POSE_COLORS[index % len(POSE_COLORS)],
                    pose=pose,
                )
            )
        self._rebuild_list(len(self._entries) - 1)
        self._sync_scene()
        self._update_counts()

    def _rebuild_list(self, select: int = -1) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for index, entry in enumerate(self._entries):
            x, y, z = entry.pose.values.position
            item = QListWidgetItem(
                f"{entry.name}    x {format_number(x, 2)}   "
                f"y {format_number(y, 2)}   z {format_number(z, 2)}"
            )
            item.setIcon(dot_icon(entry.color))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if entry.visible else Qt.Unchecked)
            item.setData(Qt.UserRole, index)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if self._entries:
            select = max(0, min(select, len(self._entries) - 1))
            self._list.setCurrentRow(select)
        self._sync_selection()

    def _sync_scene(self) -> None:
        self._scene.set_poses(
            [
                ScenePose(
                    name=entry.name,
                    color=entry.color,
                    position=entry.pose.values.position,
                    rotation=entry.pose.values.rotation,
                    visible=entry.visible,
                )
                for entry in self._entries
            ]
        )
        self._scene.set_selected(self._list.currentRow())

    def _sync_selection(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            self._value_panel.set_pose(entry.pose, entry.name, entry.color)
            self._scene.set_selected(row)
        else:
            self._value_panel.clear()
            self._scene.set_selected(-1)

    def _update_counts(self) -> None:
        total = len(self._entries)
        visible = sum(1 for entry in self._entries if entry.visible)
        self._count_badge.setText(f"{total} 帧")
        self._counts.setText(f"共 {total} 帧 · 显示 {visible} 帧")

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def _add_from_editor(self) -> None:
        try:
            poses = parse_poses(self._editor.toPlainText(), mode=self._mode)
        except MatrixParseError as exc:
            self._show_parse_hint(str(exc), DANGER)
            self._flash_status("位姿解析失败")
            return
        start = len(self._entries)
        self._append_poses(poses)
        self._show_parse_hint(f"已添加 {len(poses)} 个位姿", SUCCESS)
        self._flash_status(f"已添加 {len(poses)} 个位姿")
        if start == 0:
            self._scene.fit_view()

    def _set_mode(self, key: str) -> None:
        if key not in SAMPLES:
            return
        button = self._mode_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._mode = key
        text = self._editor.toPlainText().strip()
        samples = {sample.strip() for sample in SAMPLES.values()}
        if not text or text in samples:
            self._editor.setPlainText(SAMPLES[key].strip())
        self._editor.setPlaceholderText(PLACEHOLDERS[key])
        self._default_hint = MODE_HINTS[key]
        self._show_parse_hint(self._default_hint, MUTED)

    def _clear_editor(self) -> None:
        self._editor.clear()
        self._editor.setFocus()
        self._show_parse_hint(self._default_hint, MUTED)

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries.pop(row)
        self._rebuild_list(min(row, len(self._entries) - 1))
        self._sync_scene()
        self._update_counts()
        self._flash_status(f"已删除 {entry.name}")

    def _clear_all(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空位姿",
            f"确定清空全部 {len(self._entries)} 个位姿？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._entries.clear()
        self._rebuild_list()
        self._sync_scene()
        self._update_counts()
        self._flash_status("已清空位姿列表")

    def _on_row_changed(self, row: int) -> None:
        self._sync_selection()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if not (0 <= row < len(self._entries)):
            return
        self._entries[row].visible = item.checkState() == Qt.Checked
        self._sync_scene()
        self._update_counts()

    def _on_scene_clicked(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            self._list.setCurrentRow(index)

    # ------------------------------------------------------------------
    # 相对位姿与机器人
    # ------------------------------------------------------------------

    def _show_relative_dialog(self) -> None:
        if len(self._entries) < 2:
            QMessageBox.information(
                self, "相对位姿计算", "至少需要两个位姿才能计算相对位姿。"
            )
            return
        dialog = RelativePoseDialog(
            [(entry.name, entry.pose.matrix) for entry in self._entries], self
        )
        dialog.exec_()

    def _load_urdf(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "加载 URDF 机器人",
            "",
            "URDF 文件 (*.urdf *.xml);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            robot = load_urdf(path)
        except UrdfError as exc:
            QMessageBox.critical(self, "URDF 加载失败", str(exc))
            return
        self._apply_robot(robot)

    def _apply_robot(self, robot: UrdfRobot) -> None:
        self._close_robot_dialog()
        self._robot = robot
        self._joint_values = robot.default_values()
        self._ee_link = robot.default_ee_link()
        self._robot_target = None
        self._robot_button.setEnabled(True)
        self._refresh_robot(fit=True)
        self._show_robot_dialog()
        detail = f"已加载机器人 {robot.name} · {len(robot.movable_joints)} 个可动关节"
        if robot.warnings:
            detail += f"（{len(robot.warnings)} 条提示）"
        self._flash_status(detail)

    def _show_robot_dialog(self) -> None:
        if self._robot is None:
            self._flash_status("请先加载 URDF 机器人")
            return
        if self._robot_dialog is None:
            dialog = RobotDialog(
                self._robot,
                self._joint_values,
                self._ee_link,
                self._robot_target,
                self,
            )
            dialog.angles_changed.connect(self._on_robot_angles)
            dialog.ee_changed.connect(self._on_robot_ee_changed)
            dialog.target_changed.connect(self._on_robot_target_changed)
            dialog.clear_requested.connect(self._clear_robot)
            self._robot_dialog = dialog
            self._refresh_robot()
        self._robot_dialog.show()
        self._robot_dialog.raise_()
        self._robot_dialog.activateWindow()

    def _close_robot_dialog(self) -> None:
        if self._robot_dialog is None:
            return
        self._robot_dialog.close()
        self._robot_dialog.deleteLater()
        self._robot_dialog = None

    def _refresh_robot(self, fit: bool = False) -> None:
        if self._robot is None:
            self._scene.set_robot(None)
            return
        result = self._robot.forward(self._joint_values, self._ee_link)
        end_effector = SceneFrame(
            _translation(result.ee_matrix),
            _rotation(result.ee_matrix),
            result.ee_link,
        )
        target_frame = None
        position_error = None
        rotation_error = None
        if self._robot_target is not None:
            target_frame = SceneFrame(
                _translation(self._robot_target),
                _rotation(self._robot_target),
                "目标",
            )
            position_error = _distance(
                _translation(result.ee_matrix), _translation(self._robot_target)
            )
            rotation_error = rotation_angle_between(
                _rotation(result.ee_matrix), _rotation(self._robot_target)
            )
        skeleton = RobotSkeleton(
            name=self._robot.name,
            bones=result.segments,
            joints=result.joint_positions,
            end_effector=end_effector,
            target=target_frame,
            joint_frames=[
                SceneFrame(_translation(frame), _rotation(frame), link)
                for link, frame in result.link_frames.items()
                if link != result.ee_link and link != self._robot.root_link
            ],
        )
        self._scene.set_robot(skeleton)
        if self._robot_dialog is not None:
            self._robot_dialog.set_fk(result.ee_matrix)
            self._robot_dialog.set_error(position_error, rotation_error)
        if fit:
            self._scene.fit_view()

    def _on_robot_angles(self, values: dict) -> None:
        self._joint_values = dict(values)
        self._refresh_robot()

    def _on_robot_ee_changed(self, name: str) -> None:
        self._ee_link = name
        self._refresh_robot()

    def _on_robot_target_changed(self, matrix) -> None:
        self._robot_target = matrix
        self._refresh_robot()

    def _clear_robot(self) -> None:
        self._close_robot_dialog()
        if self._robot is None:
            return
        self._robot = None
        self._joint_values = {}
        self._ee_link = ""
        self._robot_target = None
        self._robot_button.setEnabled(False)
        self._scene.set_robot(None)
        self._scene.fit_view()
        self._flash_status("已移除机器人模型")

    # ------------------------------------------------------------------
    # 提示
    # ------------------------------------------------------------------

    def _show_parse_hint(self, text: str, color: str) -> None:
        self._parse_hint.setText(text)
        self._parse_hint.setStyleSheet(f"color: {color};")
        if text == self._default_hint:
            self._hint_timer.stop()
        else:
            self._hint_timer.start(5000)

    def _reset_hint(self) -> None:
        self._parse_hint.setText(self._default_hint)
        self._parse_hint.setStyleSheet(f"color: {MUTED};")

    def _flash_status(self, text: str) -> None:
        self._status_hint.setText(text)
        self._status_timer.start(3000)

    def _reset_status(self) -> None:
        self._status_hint.setText(DEFAULT_STATUS)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_robot_dialog()
        super().closeEvent(event)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "PoseView 使用说明",
            "<b>输入</b><br>"
            "· 顶部可切换三种方式：齐次矩阵 / 位置 + 四元数 / 位置 + 欧拉角<br>"
            "· 齐次矩阵：支持 4x4、3x4（旋转 + 平移）与 3x3（仅旋转）<br>"
            "· 位置 + 四元数：每帧 7 个数 <code>x y z qw qx qy qz</code>，四元数会自动归一化<br>"
            "· 位置 + 欧拉角：每帧 6 个数 <code>x y z roll pitch yaw</code>，角度单位为度<br>"
            "· 数字之间可用空格、逗号、分号或方括号分隔<br>"
            "· 空行或 <code>---</code> 分隔多帧，一次可添加多个位姿<br>"
            "· 4x4 最后一行须为 <code>0 0 0 1</code><br><br>"
            "<b>约定</b><br>"
            "· 右手坐标系，Z 轴向上；矩阵列向量为位姿的 X / Y / Z 轴<br>"
            "· 欧拉角为 ZYX：先绕 Z 偏航（yaw），再绕 Y 俯仰（pitch），最后绕 X 横滚（roll）<br>"
            "· 四元数按 (w, x, y, z) 显示<br><br>"
            "<b>相对位姿</b><br>"
            "· 点击顶部“相对位姿”，选择坐标系 A 与 B，计算 B 在 A 下的 4x4、位置、RPY 与四元数<br>"
            "· 交换按钮可反向计算，复制按钮导出矩阵与姿态结果<br><br>"
            "<b>机器人 / URDF</b><br>"
            "· 点击三维视图右上角“加载 URDF”，显示关节骨架与末端坐标系<br>"
            "· “关节”打开关节控制：滑条或数值框驱动正运动学，末端位姿实时更新<br>"
            "· IK 目标校验：输入目标 x y z roll pitch yaw，或取当前末端作为目标，实时查看位置 / 姿态误差<br>"
            "· 支持 revolute / continuous / prismatic / fixed 关节；仅解析骨架，不加载 mesh 外观<br>"
            "· 取消“位姿”开关可只观察机器人，不受位姿列表干扰<br><br>"
            "<b>操作</b><br>"
            "· 左键拖动旋转，右键拖动平移，滚轮缩放，双击复位<br>"
            "· 点击三维场景中的位姿原点可选中对应列表项<br>"
            "· 列表复选框控制显隐，轨迹按列表顺序连接可见位姿<br>"
            "· <code>Ctrl+Enter</code> 添加位姿，<code>Delete</code> 删除选中",
        )
