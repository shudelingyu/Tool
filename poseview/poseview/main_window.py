"""PoseView 主窗口：左侧数据面板 + 右侧三维视图。"""

from __future__ import annotations

import math

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .calc_dialog import CalcDialog
from .data_tree import DataTree, PoseEntry
from .icons import app_icon, icon, logo_pixmap, primary_icon
from .math3d import Pose, rotation_angle_between, transform_point
from .merge_dialog import MergeDialog
from .pose_input_dialog import PoseInputDialog
from .robot_dialog import RobotDialog
from .scene import (
    POSE_COLORS,
    VECTOR_COLORS,
    PoseScene,
    RobotJoint,
    RobotSkeleton,
    SceneFrame,
    SceneMarker,
    ScenePose,
    SceneVector,
    SceneVisual,
)
from .solve_panel import SolvePanel
from .urdf import UrdfError, UrdfRobot, load_urdf
from .urdf_dialog import UrdfDialog
from .vector_input_dialog import VectorInputDialog

DEFAULT_STATUS = "左键旋转 · 右键平移 · 滚轮缩放 · 双击复位"
MARKER_COLOR = "#38BDF8"
DEFAULT_VISUAL_TRIANGLE_LIMIT = 6000


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
        self._pose_entries: list[PoseEntry] = []
        self._vectors: list[SceneVector] = []
        self._robot: UrdfRobot | None = None
        self._joint_values: dict[str, float] = {}
        self._ee_link = ""
        self._robot_target: list[list[float]] | None = None
        self._show_visuals = True
        self._show_skeleton = True
        self._robot_dialog: RobotDialog | None = None
        self._calc_dialog: CalcDialog | None = None
        self._markers: list[SceneMarker] = []
        self._selected_pose = -1
        self._view_tools: list[QToolButton] = []
        self._build_ui()
        self._build_shortcuts()
        self._build_status_bar()

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status)

        self._initial_fit_timer = QTimer(self)
        self._initial_fit_timer.setSingleShot(True)
        self._initial_fit_timer.timeout.connect(self._scene.fit_view)
        self._initial_fit_timer.start(60)

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("PoseView · 位姿矩阵可视化")
        self.setWindowIcon(app_icon())
        screen = QApplication.primaryScreen().availableGeometry()
        width = max(1000, min(1480, int(screen.width() * 0.92)))
        height = max(640, min(920, int(screen.height() * 0.9)))
        self.resize(width, height)
        self.setMinimumSize(1000, 640)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 14, 14, 12)
        body_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setObjectName("BodySplitter")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._build_sidebar())
        self._splitter.addWidget(self._build_view())
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([420, 1000])
        body_layout.addWidget(self._splitter)

        outer.addWidget(body, 1)
        QTimer.singleShot(0, self._update_view_toolbar)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_view_toolbar()

    def _update_view_toolbar(self) -> None:
        if not hasattr(self, "_scene") or not self._view_tools:
            return
        compact = self._scene.width() < 760
        style = (
            Qt.ToolButtonIconOnly
            if compact
            else Qt.ToolButtonTextBesideIcon
        )
        for button in self._view_tools:
            if button.toolButtonStyle() != style:
                button.setToolButtonStyle(style)

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

        calc_button = QPushButton("计算")
        calc_button.setObjectName("Primary")
        calc_button.setIcon(primary_icon("calc", 15))
        calc_button.setCursor(Qt.PointingHandCursor)
        calc_button.setToolTip("坐标变换、位姿测量、变换链、旋转四元数与数据工具")
        calc_button.clicked.connect(self._show_calc_dialog)
        layout.addWidget(calc_button)

        help_button = QPushButton("使用说明")
        help_button.setObjectName("Ghost")
        help_button.setIcon(icon("help", "#475569", 15))
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self._show_help)
        layout.addWidget(help_button)
        return header

    def _build_sidebar(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(350)
        scroll.setMaximumWidth(600)

        container = QWidget()
        container.setObjectName("Sidebar")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_add_card())
        layout.addWidget(self._build_tree_card(), 1)
        self._solve_panel = SolvePanel()
        layout.addWidget(self._solve_panel)

        scroll.setWidget(container)
        return scroll

    def _build_add_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 12)
        card_layout.setSpacing(8)

        title = QLabel("添加数据")
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(6)
        for text, icon_name, slot, tooltip in (
            ("位姿", "axis", self._add_poses_dialog, "录入位姿矩阵、四元数或欧拉角"),
            ("向量", "vector", self._add_vectors_dialog, "录入带起点的向量"),
            ("URDF", "file", self._load_urdf, "加载 URDF 机器人"),
            ("拼接", "link", self._merge_urdf, "把附加 URDF 接到当前机器人"),
        ):
            button = QPushButton(text)
            button.setObjectName("Primary")
            button.setIcon(primary_icon(icon_name, 15))
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            row.addWidget(button, 1)
        card_layout.addLayout(row)
        return card

    def _build_tree_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 12)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("数据列表")
        title.setObjectName("SectionTitle")
        hint = QLabel("双击重命名")
        hint.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
        card_layout.addLayout(head)

        self._tree = DataTree()
        self._tree.setMinimumHeight(240)
        self._tree.pose_selected.connect(self._on_pose_selected)
        self._tree.vector_selected.connect(self._on_vector_selected)
        self._tree.robot_selected.connect(self._on_robot_tree_selected)
        self._tree.poses_changed.connect(self._on_tree_poses_changed)
        self._tree.vectors_changed.connect(self._on_tree_vectors_changed)
        self._tree.pose_axis_vector_requested.connect(
            self._on_pose_axis_vector
        )
        self._tree.robot_visuals_toggled.connect(self._on_visuals_toggled)
        self._tree.robot_skeleton_toggled.connect(self._on_skeleton_toggled)
        self._tree.robot_panel_requested.connect(self._show_robot_dialog)
        self._tree.robot_joint_requested.connect(self._on_robot_joint_requested)
        self._tree.robot_joint_value_changed.connect(self._on_tree_joint_value)
        self._tree.robot_remove_requested.connect(self._clear_robot)
        card_layout.addWidget(self._tree, 1)
        return card

    def _build_view(self) -> QFrame:
        self._scene = PoseScene()
        self._scene.pose_clicked.connect(self._on_scene_clicked)
        self._scene.robot_item_selected.connect(self._on_robot_item_selected)

        card = QFrame()
        card.setObjectName("ViewCard")
        card.setMinimumWidth(480)
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
            checkable=True, checked=True, tooltip="显示 / 隐藏场景中的位姿坐标轴",
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
                checkable=True, checked=True, tooltip="显示 / 隐藏位姿与向量名称",
            )
        )
        bar_layout.addWidget(
            self._view_button(
                "测量", "ruler", self._toggle_measure,
                checkable=True, checked=False,
                tooltip="点击地面取点：两点测距、三点测角，Esc 清除",
            )
        )
        self._robot_button = self._view_button(
            "关节", "robot", lambda: self._show_robot_dialog(),
            tooltip="打开关节控制与 IK 校验（需先加载 URDF）",
        )
        self._robot_button.setEnabled(False)
        bar_layout.addWidget(self._robot_button)
        bar_layout.addWidget(
            self._view_button(
                "截图", "camera", self._save_screenshot,
                tooltip="导出当前三维视图截图",
            )
        )

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
        self._view_tools.append(button)
        return button

    def _build_shortcuts(self) -> None:
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._show_help)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self._status_hint = QLabel(DEFAULT_STATUS)
        self._counts = QLabel("位姿 0/0 · 向量 0/0")
        status.addWidget(self._status_hint, 1)
        status.addPermanentWidget(self._counts)

    # ------------------------------------------------------------------
    # 位姿
    # ------------------------------------------------------------------

    def _add_poses_dialog(self) -> None:
        dialog = PoseInputDialog(self)
        if dialog.exec_() != dialog.Accepted or not dialog.poses:
            return
        start = len(self._pose_entries)
        for offset, pose in enumerate(dialog.poses):
            index = start + offset
            self._pose_entries.append(
                PoseEntry(
                    f"位姿 {index + 1}",
                    POSE_COLORS[index % len(POSE_COLORS)],
                    pose,
                )
            )
        self._refresh_pose_tree(select=start)
        self._scene.fit_view()
        self._flash_status(f"已添加 {len(dialog.poses)} 个位姿")

    def _add_pose_entry(
        self, matrix: list[list[float]], name: str = "", visible: bool = True
    ) -> None:
        index = len(self._pose_entries)
        self._pose_entries.append(
            PoseEntry(
                name or f"位姿 {index + 1}",
                POSE_COLORS[index % len(POSE_COLORS)],
                Pose(matrix),
                visible,
            )
        )
        self._refresh_pose_tree(select=index)

    def _refresh_pose_tree(self, select: int | None = None) -> None:
        target = self._selected_pose if select is None else select
        if target >= len(self._pose_entries):
            target = len(self._pose_entries) - 1
        self._tree.set_poses(
            self._pose_entries, select=target if target >= 0 else None
        )
        self._sync_pose_scene()
        self._solve_panel.set_poses(self._pose_entries)
        self._selected_pose = target
        self._solve_panel.select_pose(target)
        self._update_counts()
        if self._calc_dialog is not None:
            self._calc_dialog.set_pose_entries(self._pose_entries)

    def _sync_pose_scene(self) -> None:
        self._scene.set_poses(
            [
                ScenePose(
                    name=entry.name,
                    color=entry.color,
                    position=entry.pose.values.position,
                    rotation=entry.pose.values.rotation,
                    visible=entry.visible,
                )
                for entry in self._pose_entries
            ]
        )

    def _on_tree_poses_changed(self, entries: list) -> None:
        self._pose_entries = list(entries)
        self._sync_pose_scene()
        self._solve_panel.set_poses(self._pose_entries)
        if self._selected_pose >= len(self._pose_entries):
            self._selected_pose = len(self._pose_entries) - 1
        self._solve_panel.select_pose(self._selected_pose)
        self._scene.set_selected(self._selected_pose)
        self._update_counts()
        if self._calc_dialog is not None:
            self._calc_dialog.set_pose_entries(self._pose_entries)

    def _on_pose_selected(self, index: int) -> None:
        self._selected_pose = index
        self._scene.set_selected(index)
        self._solve_panel.select_pose(index)
        if 0 <= index < len(self._pose_entries):
            entry = self._pose_entries[index]
            x, y, z = entry.pose.values.position
            self._flash_status(
                f"位姿 {entry.name} · x {x:.4f}  y {y:.4f}  z {z:.4f}"
            )

    def _on_scene_clicked(self, index: int) -> None:
        if 0 <= index < len(self._pose_entries):
            self._tree.select_pose(index)

    # ------------------------------------------------------------------
    # 向量
    # ------------------------------------------------------------------

    def _add_vectors_dialog(self) -> None:
        dialog = VectorInputDialog(self)
        if dialog.exec_() != dialog.Accepted or not dialog.vectors:
            return
        start = len(self._vectors)
        for offset, (start_point, direction) in enumerate(dialog.vectors):
            index = start + offset
            self._vectors.append(
                SceneVector(
                    f"向量 {index + 1}",
                    VECTOR_COLORS[index % len(VECTOR_COLORS)],
                    start_point,
                    direction,
                )
            )
        self._refresh_vector_tree(select=start)
        self._scene.fit_view()
        self._flash_status(f"已添加 {len(dialog.vectors)} 个向量")

    def _add_vector_entry(
        self,
        start,
        direction,
        name: str = "",
        source: str = "",
        axis: str = "",
    ) -> str:
        length = math.sqrt(
            direction[0] ** 2 + direction[1] ** 2 + direction[2] ** 2
        )
        if length < 1e-9:
            return ""
        index = len(self._vectors)
        vector = SceneVector(
            name or f"向量 {index + 1}",
            VECTOR_COLORS[index % len(VECTOR_COLORS)],
            start,
            direction,
            source=source,
            axis=axis,
        )
        self._vectors.append(vector)
        self._refresh_vector_tree(select=index)
        return vector.name

    def _refresh_vector_tree(self, select: int | None = None) -> None:
        self._tree.set_vectors(self._vectors, select=select)
        self._scene.set_vectors(self._vectors)
        self._update_counts()
        if self._calc_dialog is not None:
            self._calc_dialog.set_vector_entries(self._vectors)

    def _on_tree_vectors_changed(self, vectors: list) -> None:
        self._vectors = list(vectors)
        self._scene.set_vectors(self._vectors)
        self._update_counts()
        if self._calc_dialog is not None:
            self._calc_dialog.set_vector_entries(self._vectors)

    def _on_vector_selected(self, index: int) -> None:
        if 0 <= index < len(self._vectors):
            vector = self._vectors[index]
            length = math.sqrt(
                vector.direction[0] ** 2
                + vector.direction[1] ** 2
                + vector.direction[2] ** 2
            )
            self._flash_status(f"向量 {vector.name} · 模长 {length:.4f}")

    def _on_pose_axis_vector(self, index: int, axis: str) -> None:
        """以位姿坐标系原点为起点，把指定坐标轴添加为向量。"""
        if not (0 <= index < len(self._pose_entries)):
            return
        entry = self._pose_entries[index]
        column = {"x": 0, "y": 1, "z": 2}.get(axis)
        if column is None:
            return
        matrix = entry.pose.matrix
        direction = (
            matrix[0][column],
            matrix[1][column],
            matrix[2][column],
        )
        name = f"{entry.name} · {axis.upper()} 轴"
        vector_name = self._add_vector_entry(
            entry.pose.values.position,
            direction,
            name,
            source=entry.tag,
            axis=axis,
        )
        if vector_name:
            self._flash_status(f"已添加轴向量 {vector_name}")
        else:
            self._flash_status("该坐标轴为零向量，未添加")

    def _sync_axis_vectors(self) -> bool:
        """让位姿坐标轴生成的向量跟随源坐标系（含关节运动）。"""
        entries = {
            entry.tag: entry for entry in self._pose_entries if entry.tag
        }
        changed = False
        for vector in self._vectors:
            if not vector.source or not vector.axis:
                continue
            entry = entries.get(vector.source)
            if entry is None:
                continue
            column = {"x": 0, "y": 1, "z": 2}.get(vector.axis)
            if column is None:
                continue
            matrix = entry.pose.matrix
            start = entry.pose.values.position
            direction = (
                matrix[0][column],
                matrix[1][column],
                matrix[2][column],
            )
            if vector.start != start or vector.direction != direction:
                vector.start = start
                vector.direction = direction
                changed = True
        return changed

    # ------------------------------------------------------------------
    # 计算工具
    # ------------------------------------------------------------------

    def _show_calc_dialog(self) -> None:
        if self._calc_dialog is None:
            dialog = CalcDialog(self)
            dialog.pose_created.connect(self._on_calc_pose_created)
            dialog.point_added.connect(self._on_calc_point_added)
            dialog.vector_added.connect(self._on_calc_vector_added)
            dialog.poses_imported.connect(self._on_poses_imported)
            dialog.markers_cleared.connect(self._clear_markers)
            dialog.set_pose_entries(self._pose_entries)
            dialog.set_vector_entries(self._vectors)
            self._calc_dialog = dialog
        else:
            self._calc_dialog.set_pose_entries(self._pose_entries)
            self._calc_dialog.set_vector_entries(self._vectors)
        self._calc_dialog.show()
        self._calc_dialog.raise_()
        self._calc_dialog.activateWindow()

    def _close_calc_dialog(self) -> None:
        if self._calc_dialog is None:
            return
        self._calc_dialog.close()
        self._calc_dialog.deleteLater()
        self._calc_dialog = None

    def _on_calc_pose_created(self, matrix, name: str) -> None:
        self._add_pose_entry(matrix, name)
        self._flash_status(f"已添加位姿 {name}")

    def _on_calc_point_added(self, name: str, position) -> None:
        self._markers.append(SceneMarker(name, MARKER_COLOR, position))
        self._scene.set_markers(self._markers)
        self._flash_status(f"已添加标注 {name}")

    def _on_calc_vector_added(self, name: str, start, direction) -> None:
        vector_name = self._add_vector_entry(start, direction, name)
        if not vector_name:
            self._flash_status("变换结果为零向量，未添加")
            return
        self._flash_status(f"已添加向量 {vector_name}")

    def _on_poses_imported(self, items: list) -> None:
        if not items:
            return
        start = len(self._pose_entries)
        for offset, (name, matrix) in enumerate(items):
            index = start + offset
            self._pose_entries.append(
                PoseEntry(
                    name or f"位姿 {index + 1}",
                    POSE_COLORS[index % len(POSE_COLORS)],
                    Pose(matrix),
                )
            )
        self._refresh_pose_tree(select=start)
        self._flash_status(f"已导入 {len(items)} 个位姿")

    def _clear_markers(self) -> None:
        if not self._markers:
            return
        self._markers.clear()
        self._scene.set_markers([])
        self._flash_status("已清除场景标注")

    # ------------------------------------------------------------------
    # 测量与截图
    # ------------------------------------------------------------------

    def _toggle_measure(self, enabled: bool) -> None:
        self._scene.set_measure_mode(enabled)
        if enabled:
            self._flash_status("测量模式：点击地面取点，两点测距、三点测角")
        else:
            self._flash_status("已退出测量模式")

    def _save_screenshot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出三维视图截图",
            "poseview.png",
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        if self._scene.grab().save(path):
            self._flash_status(f"已保存截图：{path}")
        else:
            QMessageBox.warning(
                self, "导出失败", "无法保存图片，请检查路径与权限。"
            )

    # ------------------------------------------------------------------
    # 机器人
    # ------------------------------------------------------------------

    def _load_urdf(self) -> None:
        dialog = UrdfDialog(self)
        if dialog.exec_() != dialog.Accepted:
            return
        try:
            robot = load_urdf(dialog.path)
        except UrdfError as exc:
            QMessageBox.critical(self, "URDF 加载失败", str(exc))
            return
        self._apply_robot(robot)

    def _merge_urdf(self) -> None:
        if self._robot is None:
            self._flash_status("请先加载主机器人，再拼接附加 URDF")
            return
        dialog = MergeDialog(self._robot, self)
        if dialog.exec_() != dialog.Accepted or dialog.merged_robot is None:
            return
        merged = dialog.merged_robot
        values = merged.default_values()
        for name, value in self._joint_values.items():
            if name in values:
                values[name] = value
        self._apply_robot(merged, values)
        detail = (
            f"已拼接 {merged.name} · {len(merged.link_names)} 个 link · "
            f"{len(merged.movable_joints)} 个可动关节"
        )
        if merged.warnings:
            detail += f"（{len(merged.warnings)} 条提示）"
        self._flash_status(detail)

    def _apply_robot(
        self, robot: UrdfRobot, values: dict[str, float] | None = None
    ) -> None:
        self._close_robot_dialog()
        self._robot = robot
        self._joint_values = (
            dict(values) if values is not None else robot.default_values()
        )
        self._ee_link = robot.default_ee_link()
        self._robot_target = None
        self._selected_pose = -1
        self._robot_button.setEnabled(True)
        show_visuals = (
            robot.visual_triangle_count <= DEFAULT_VISUAL_TRIANGLE_LIMIT
        )
        self._show_visuals = show_visuals
        self._show_skeleton = True
        self._scene.set_show_visuals(show_visuals)
        self._scene.set_show_skeleton(True)
        self._tree.set_robot(
            robot.name,
            bool(robot.visuals),
            show_visuals,
            self._joint_tree_items(robot),
            skeleton_visible=True,
        )
        pose_count = self._add_joint_poses(robot)
        self._refresh_robot(fit=True)
        self._show_robot_dialog(show_visuals)
        detail = f"已加载机器人 {robot.name} · {len(robot.movable_joints)} 个可动关节"
        if pose_count:
            detail += f" · 已保存 {pose_count} 个关节坐标系"
        if robot.warnings:
            detail += f"（{len(robot.warnings)} 条提示）"
        if robot.visuals and not show_visuals:
            detail += (
                f" · 外观 {robot.visual_triangle_count} 个三角面，"
                "已默认关闭，可在机器人节点勾选开启"
            )
        self._flash_status(detail)

    def _show_robot_dialog(self, show_visuals: bool | None = None) -> None:
        if self._robot is None:
            self._flash_status("请先加载 URDF 机器人")
            return
        if self._robot_dialog is None:
            dialog = RobotDialog(
                self._robot,
                self._joint_values,
                self._ee_link,
                self._robot_target,
                self._show_visuals
                if show_visuals is None
                else show_visuals,
                self,
                show_skeleton=self._show_skeleton,
            )
            dialog.angles_changed.connect(self._on_robot_angles)
            dialog.ee_changed.connect(self._on_robot_ee_changed)
            dialog.target_changed.connect(self._on_robot_target_changed)
            dialog.clear_requested.connect(self._clear_robot)
            dialog.visuals_toggled.connect(self._on_visuals_toggled)
            dialog.skeleton_toggled.connect(self._on_skeleton_toggled)
            self._robot_dialog = dialog
            self._refresh_robot()
        self._robot_dialog.set_visuals_visible(self._show_visuals)
        self._robot_dialog.set_skeleton_visible(self._show_skeleton)
        self._robot_dialog.show()
        self._robot_dialog.raise_()
        self._robot_dialog.activateWindow()

    @staticmethod
    def _joint_limits(joint) -> tuple[float, float]:
        """关节滑条对应的有效范围（弧度或米）。"""
        lower, upper = joint.lower, joint.upper
        if (
            not (math.isfinite(lower) and math.isfinite(upper))
            or upper - lower < 1e-9
        ):
            if joint.type in ("revolute", "continuous"):
                return -math.pi, math.pi
            return -0.5, 0.5
        return lower, upper

    def _joint_tree_items(
        self, robot: UrdfRobot
    ) -> list[tuple[str, str, str, int, bool]]:
        """机器人节点下的关节控制行：名称、当前值、提示、滑条位置、可用。"""
        items: list[tuple[str, str, str, int, bool]] = []
        for joint in robot.movable_joints:
            value = robot.effective_value(joint, self._joint_values)
            lower, upper = self._joint_limits(joint)
            position = round((value - lower) / (upper - lower) * 1000)
            position = max(0, min(1000, position))
            if joint.type in ("revolute", "continuous"):
                text = f"{math.degrees(value):.1f}°"
                limits = (
                    f"限位 [{math.degrees(lower):.1f}°, "
                    f"{math.degrees(upper):.1f}°]"
                )
            else:
                text = f"{value:.3f} m"
                limits = f"限位 [{lower:.3f}, {upper:.3f}] m"
            if joint.mimic:
                text += " · 联动"
                tooltip = (
                    f"{joint.name} · {joint.type}\n"
                    f"跟随 {joint.mimic}（×{joint.mimic_multiplier:g} + "
                    f"{joint.mimic_offset:g}）\n{limits}\n拖动滑条或打开关节控制"
                )
            else:
                tooltip = (
                    f"{joint.name} · {joint.type}\n当前 {text}\n{limits}\n"
                    "拖动滑条直接控制，右侧按钮打开关节控制"
                )
            items.append(
                (joint.name, text, tooltip, position, not joint.is_mimic)
            )
        return items

    def _on_tree_joint_value(self, name: str, value: int) -> None:
        if self._robot is None:
            return
        joint = next(
            (
                item
                for item in self._robot.movable_joints
                if item.name == name
            ),
            None,
        )
        if joint is None or joint.is_mimic:
            return
        lower, upper = self._joint_limits(joint)
        ratio = max(0, min(1000, value)) / 1000.0
        self._joint_values[name] = lower + (upper - lower) * ratio
        self._refresh_robot()

    def _on_robot_joint_requested(self, name: str) -> None:
        if self._robot is None:
            return
        self._show_robot_dialog()
        if self._robot_dialog is not None:
            self._robot_dialog.select_joint(name)

    def _add_joint_poses(self, robot: UrdfRobot) -> int:
        """各关节坐标系加入位姿列表，默认隐藏，随关节运动同步更新。"""
        self._pose_entries = [
            entry
            for entry in self._pose_entries
            if not entry.tag.startswith("joint:")
        ]
        result = robot.forward(self._joint_values, self._ee_link)
        added = 0
        for joint in robot.joints:
            if joint.child not in result.link_frames:
                continue
            index = len(self._pose_entries)
            self._pose_entries.append(
                PoseEntry(
                    f"{robot.name} · {joint.name}",
                    POSE_COLORS[index % len(POSE_COLORS)],
                    Pose(result.link_frames[joint.child]),
                    visible=False,
                    tag=f"joint:{joint.name}",
                )
            )
            added += 1
        if added:
            self._refresh_pose_tree()
        return added

    def _update_joint_poses(self, result) -> bool:
        """把最新的关节坐标系（子连杆坐标系）矩阵同步到位姿列表。"""
        mapping = {
            entry.tag: entry
            for entry in self._pose_entries
            if entry.tag.startswith("joint:")
        }
        changed = False
        for joint in self._robot.joints:
            entry = mapping.get(f"joint:{joint.name}")
            frame = result.link_frames.get(joint.child)
            if entry is None or frame is None:
                continue
            if entry.pose.matrix != frame:
                entry.pose = Pose(frame)
                changed = True
        return changed

    def _on_visuals_toggled(self, enabled: bool) -> None:
        self._show_visuals = bool(enabled)
        self._scene.set_show_visuals(self._show_visuals)
        if self._robot_dialog is not None:
            self._robot_dialog.set_visuals_visible(self._show_visuals)
        self._refresh_robot()

    def _on_skeleton_toggled(self, enabled: bool) -> None:
        self._show_skeleton = bool(enabled)
        self._scene.set_show_skeleton(self._show_skeleton)
        self._tree.set_robot_skeleton_visible(self._show_skeleton)
        if self._robot_dialog is not None:
            self._robot_dialog.set_skeleton_visible(self._show_skeleton)

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
        visuals: list[SceneVisual] = []
        if self._show_visuals:
            for visual in self._robot.visuals:
                frame = result.link_frames.get(visual.link)
                if frame is None:
                    continue
                triangles = [
                    tuple(
                        transform_point(frame, vertex) for vertex in triangle
                    )
                    for triangle in visual.triangles
                ]
                red, green, blue, alpha = visual.color
                color = "#{:02X}{:02X}{:02X}".format(
                    round(red * 255), round(green * 255), round(blue * 255)
                )
                visuals.append(
                    SceneVisual(visual.link, color, alpha, triangles)
                )
        joints_info = [
            RobotJoint(
                info.name,
                info.type,
                info.position,
                info.axis,
                info.lower,
                info.upper,
                info.value,
            )
            for info in result.joint_infos
        ]
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
            visuals=visuals,
            bone_links=list(result.segment_links),
            joints_info=joints_info,
        )
        self._scene.set_robot(skeleton)
        self._tree.update_robot_joints(self._joint_tree_items(self._robot))
        poses_changed = self._update_joint_poses(result)
        vectors_changed = self._sync_axis_vectors()
        if poses_changed:
            self._sync_pose_scene()
            self._solve_panel.set_poses(self._pose_entries)
            if self._selected_pose >= 0:
                self._solve_panel.select_pose(self._selected_pose)
            self._tree.refresh_pose_positions(self._pose_entries)
            if self._calc_dialog is not None:
                self._calc_dialog.set_pose_entries(self._pose_entries)
        if vectors_changed:
            self._scene.set_vectors(self._vectors)
            self._tree.refresh_vector_tooltips(self._vectors)
            if self._calc_dialog is not None:
                self._calc_dialog.set_vector_entries(self._vectors)
        if self._robot_dialog is not None:
            self._robot_dialog.apply_values(self._joint_values)
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

    def _on_robot_tree_selected(self) -> None:
        if self._robot is None:
            return
        self._flash_status(
            f"机器人 {self._robot.name} · 双击打开关节控制"
        )

    def _on_robot_item_selected(self, kind: str, name: str) -> None:
        if self._robot is None:
            return
        if kind == "joint":
            joint = next(
                (
                    item
                    for item in self._robot.joints
                    if item.name == name
                ),
                None,
            )
            if joint is None:
                return
            value = self._robot.effective_value(joint, self._joint_values)
            suffix = f" · 联动 ← {joint.mimic}" if joint.mimic else ""
            if joint.type in ("revolute", "continuous"):
                text = (
                    f"关节 {name} · {math.degrees(value):.1f}° · "
                    f"限位 [{math.degrees(joint.lower):.1f}°, "
                    f"{math.degrees(joint.upper):.1f}°]{suffix}"
                )
            elif joint.type == "prismatic":
                text = (
                    f"关节 {name} · {value:.3f} m · "
                    f"限位 [{joint.lower:.3f}, {joint.upper:.3f}] m{suffix}"
                )
            else:
                text = f"关节 {name}{suffix}"
        else:
            text = f"连杆 {name}"
        self._flash_status(text)

    def _clear_robot(self) -> None:
        self._close_robot_dialog()
        if self._robot is None:
            return
        self._robot = None
        self._joint_values = {}
        self._ee_link = ""
        self._robot_target = None
        self._robot_button.setEnabled(False)
        before = len(self._pose_entries)
        self._pose_entries = [
            entry
            for entry in self._pose_entries
            if not entry.tag.startswith("joint:")
        ]
        self._scene.set_robot(None)
        self._tree.clear_robot()
        if len(self._pose_entries) != before:
            self._selected_pose = min(
                self._selected_pose, len(self._pose_entries) - 1
            )
            self._refresh_pose_tree(
                select=self._selected_pose
                if self._selected_pose >= 0
                else None
            )
        else:
            self._sync_pose_scene()
            self._update_counts()
        self._scene.fit_view()
        self._flash_status("已移除机器人模型")

    # ------------------------------------------------------------------
    # 提示
    # ------------------------------------------------------------------

    def _update_counts(self) -> None:
        pose_total = len(self._pose_entries)
        pose_visible = sum(1 for entry in self._pose_entries if entry.visible)
        vector_total = len(self._vectors)
        vector_visible = sum(1 for vector in self._vectors if vector.visible)
        self._counts.setText(
            f"位姿 {pose_visible}/{pose_total} · "
            f"向量 {vector_visible}/{vector_total}"
        )

    def _flash_status(self, text: str) -> None:
        self._status_hint.setText(text)
        self._status_timer.start(3000)

    def _reset_status(self) -> None:
        self._status_hint.setText(DEFAULT_STATUS)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_robot_dialog()
        self._close_calc_dialog()
        super().closeEvent(event)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "PoseView 使用说明",
            "<b>左侧添加数据</b><br>"
            "· “位姿”按钮：独立输入框，支持齐次矩阵 / 位置 + 四元数 / 位置 + 欧拉角 / 位置 + 旋转向量<br>"
            "· 齐次矩阵支持 4x4、3x4（旋转 + 平移）与 3x3（仅旋转）；空行或 <code>---</code> 分隔多帧<br>"
            "· “向量”按钮：独立输入框，支持“起点 + 方向”或“起点 + 终点”，每行 6 个数<br>"
            "· “URDF”按钮：输入或浏览 URDF 文件路径，加载后显示在机器人节点<br>"
            "· “拼接”按钮：把附加 URDF 的根 link 通过固定关节接到当前机器人，可设置安装 link、前缀与安装位姿<br><br>"
            "<b>数据列表</b><br>"
            "· 根节点“位姿 / 向量 / 机器人”可展开或收起，右键可全部展开 / 收起<br>"
            "· 子项复选框控制场景显隐，双击或右键重命名，Delete 或右键菜单删除<br>"
            "· 选中位姿会在下方显示姿态解算；点击三维场景中的位姿会同步选中<br>"
            "· 位姿右键“添加轴向量”：以该坐标系原点为起点，把 X / Y / Z 轴添加为向量，关节运动时自动跟随<br>"
            "· 机器人节点复选框控制外观，“骨架坐标系”子项单独控制骨架、关节轴与连杆坐标系<br>"
            "· 机器人节点展开后列出可动关节，拖动滑条直接控制关节，右侧按钮打开关节控制并定位<br>"
            "· 机器人节点右键可打开关节控制、显示 / 隐藏外观或移除机器人<br><br>"
            "<b>姿态解算</b><br>"
            "· 显示选中位姿的位置、RPY、四元数、轴角与旋转向量，可复制<br><br>"
            "<b>机器人 / URDF</b><br>"
            "· 加载时会把各关节坐标系加入位姿列表，名称形如 <code>机器人名 · 关节名</code>，默认隐藏<br>"
            "· 拖动关节或求解 IK 时，这些关节坐标系的矩阵与场景显示会实时同步<br>"
            "· 外观支持 box / cylinder / sphere 与 STL / OBJ mesh，颜色取自 URDF material<br>"
            "· 关节控制：滑条或数值框驱动正运动学，支持关节锁定、目标位姿与 IK 求解<br>"
            "· 点击场景中的连杆或关节可选中高亮，状态栏显示关节角度与限位<br><br>"
            "<b>计算工具</b><br>"
            "· 点击右上角“计算”打开，包含点位变换、位姿测量、相对位姿、向量、变换链、旋转 / 四元数、数据 / 轨迹<br>"
            "· 相对位姿：选择坐标系 A / B，计算 <code>T_A→B = inv(T_A) · T_B</code>，下方展示 A / B 原始参数并可复制<br>"
            "· 向量：选择两个向量计算夹角、cos θ、点积、模长、单位向量、叉积与投影，下方展示原始参数并可复制<br>"
            "· 计算结果可加入为位姿、向量或场景标注<br><br>"
            "<b>操作</b><br>"
            "· 左键拖动旋转，右键拖动平移，滚轮缩放，双击复位<br>"
            "· 工具栏“测量”进入测量模式：点击地面取点，两点测距、三点测角，<code>Esc</code> 清除<br>"
            "· 工具栏“截图”导出当前三维视图<br>"
            "· <code>F1</code> 打开本说明",
        )
