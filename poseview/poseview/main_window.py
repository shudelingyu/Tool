"""PoseView 主窗口。"""

from __future__ import annotations

import math

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .calc_dialog import CalcDialog
from .icons import app_icon, icon, logo_pixmap, primary_icon
from .math3d import rotation_angle_between, transform_point
from .pose_vector_dialog import PoseVectorDialog
from .robot_dialog import RobotDialog
from .scene import (
    PoseScene,
    RobotJoint,
    RobotSkeleton,
    SceneFrame,
    SceneMarker,
    ScenePose,
    SceneVector,
    SceneVisual,
)
from .urdf import UrdfError, UrdfRobot, load_urdf

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
        self._pose_entries: list = []
        self._robot: UrdfRobot | None = None
        self._joint_values: dict[str, float] = {}
        self._ee_link = ""
        self._robot_target: list[list[float]] | None = None
        self._show_visuals = True
        self._robot_dialog: RobotDialog | None = None
        self._vectors: list[SceneVector] = []
        self._tool_dialog: PoseVectorDialog | None = None
        self._calc_dialog: CalcDialog | None = None
        self._markers: list[SceneMarker] = []
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
        self.resize(1360, 880)
        self.setMinimumSize(1040, 660)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(14, 14, 14, 12)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(self._build_view())
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

        tool_button = QPushButton("位姿 · 向量")
        tool_button.setObjectName("Primary")
        tool_button.setIcon(primary_icon("axis", 15))
        tool_button.setCursor(Qt.PointingHandCursor)
        tool_button.setToolTip("打开位姿与向量面板：位姿输入/解算/相对位姿，向量与夹角")
        tool_button.clicked.connect(lambda: self._show_pose_vector_dialog())
        layout.addWidget(tool_button)

        calc_button = QPushButton("计算")
        calc_button.setObjectName("Primary")
        calc_button.setIcon(primary_icon("calc", 15))
        calc_button.setCursor(Qt.PointingHandCursor)
        calc_button.setToolTip("坐标变换、位姿测量、变换链、旋转四元数与数据工具")
        calc_button.clicked.connect(self._show_calc_dialog)
        layout.addWidget(calc_button)

        urdf_button = QPushButton("URDF")
        urdf_button.setObjectName("Primary")
        urdf_button.setIcon(primary_icon("file", 15))
        urdf_button.setCursor(Qt.PointingHandCursor)
        urdf_button.setToolTip("加载 URDF 机器人，显示关节骨架")
        urdf_button.clicked.connect(self._load_urdf)
        layout.addWidget(urdf_button)

        help_button = QPushButton("使用说明")
        help_button.setObjectName("Ghost")
        help_button.setIcon(icon("help", "#475569", 15))
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self._show_help)
        layout.addWidget(help_button)
        return header

    def _build_view(self) -> QFrame:
        self._scene = PoseScene()
        self._scene.pose_clicked.connect(self._on_scene_clicked)
        self._scene.robot_item_selected.connect(self._on_robot_item_selected)

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
            "关节", "robot", self._show_robot_dialog,
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
        return button

    def _build_shortcuts(self) -> None:
        pose_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        pose_shortcut.activated.connect(lambda: self._show_pose_vector_dialog(0))
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._show_help)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self._status_hint = QLabel(DEFAULT_STATUS)
        self._counts = QLabel("共 0 帧 · 显示 0 帧")
        status.addWidget(self._status_hint, 1)
        status.addPermanentWidget(self._counts)

    # ------------------------------------------------------------------
    # 位姿与向量面板
    # ------------------------------------------------------------------

    def _ensure_tool_dialog(self) -> PoseVectorDialog:
        if self._tool_dialog is None:
            dialog = PoseVectorDialog(self)
            dialog.poses_changed.connect(self._on_poses_changed)
            dialog.selection_changed.connect(self._on_pose_selection_changed)
            dialog.vectors_changed.connect(self._on_vectors_changed)
            self._tool_dialog = dialog
        return self._tool_dialog

    def _show_pose_vector_dialog(self, tab: int | None = None) -> None:
        dialog = self._ensure_tool_dialog()
        if tab is not None:
            dialog.set_tab(tab)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_tool_dialog(self) -> None:
        if self._tool_dialog is None:
            return
        self._tool_dialog.close()
        self._tool_dialog.deleteLater()
        self._tool_dialog = None

    def _on_poses_changed(self, entries: list) -> None:
        was_empty = not self._pose_entries
        self._pose_entries = list(entries)
        self._sync_scene()
        self._update_counts()
        if self._calc_dialog is not None:
            self._calc_dialog.set_pose_entries(self._pose_entries)
        if was_empty and self._pose_entries:
            self._scene.fit_view()

    def _on_pose_selection_changed(self, index: int) -> None:
        self._scene.set_selected(index)

    def _on_scene_clicked(self, index: int) -> None:
        if not (0 <= index < len(self._pose_entries)):
            return
        self._show_pose_vector_dialog(0)
        if self._tool_dialog is not None:
            self._tool_dialog.select_row(index)

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
                for entry in self._pose_entries
            ]
        )

    def _update_counts(self) -> None:
        total = len(self._pose_entries)
        visible = sum(1 for entry in self._pose_entries if entry.visible)
        self._counts.setText(f"共 {total} 帧 · 显示 {visible} 帧")

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
            self._calc_dialog = dialog
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
        dialog = self._ensure_tool_dialog()
        dialog.add_pose(matrix, name)
        self._flash_status(f"已添加位姿 {name}")

    def _on_calc_point_added(self, name: str, position) -> None:
        self._markers.append(SceneMarker(name, MARKER_COLOR, position))
        self._scene.set_markers(self._markers)
        self._flash_status(f"已添加标注 {name}")

    def _on_calc_vector_added(self, name: str, start, direction) -> None:
        dialog = self._ensure_tool_dialog()
        vector_name = dialog.add_vector(start, direction, name)
        if not vector_name:
            self._flash_status("变换结果为零向量，未添加")
            return
        self._flash_status(f"已添加向量 {vector_name}")

    def _on_poses_imported(self, items: list) -> None:
        dialog = self._ensure_tool_dialog()
        count = dialog.add_poses(items)
        self._flash_status(f"已导入 {count} 个位姿")

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
        show_visuals = (
            robot.visual_triangle_count <= DEFAULT_VISUAL_TRIANGLE_LIMIT
        )
        self._show_visuals = show_visuals
        self._scene.set_show_visuals(show_visuals)
        pose_count = self._add_joint_poses(robot)
        self._refresh_robot(fit=True)
        self._show_robot_dialog(show_visuals)
        detail = f"已加载机器人 {robot.name} · {len(robot.movable_joints)} 个可动关节"
        if pose_count:
            detail += f" · 已添加 {pose_count} 个关节位姿"
        if robot.warnings:
            detail += f"（{len(robot.warnings)} 条提示）"
        if robot.visuals and not show_visuals:
            detail += (
                f" · 外观 {robot.visual_triangle_count} 个三角面，"
                "已默认关闭，可在关节面板的“外观”开启"
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
                True if show_visuals is None else show_visuals,
                self,
            )
            dialog.angles_changed.connect(self._on_robot_angles)
            dialog.ee_changed.connect(self._on_robot_ee_changed)
            dialog.target_changed.connect(self._on_robot_target_changed)
            dialog.clear_requested.connect(self._clear_robot)
            dialog.visuals_toggled.connect(self._on_visuals_toggled)
            self._robot_dialog = dialog
            self._refresh_robot()
        self._robot_dialog.show()
        self._robot_dialog.raise_()
        self._robot_dialog.activateWindow()

    def _add_joint_poses(self, robot: UrdfRobot) -> int:
        """把当前各关节坐标系作为位姿加入位姿列表。"""
        result = robot.forward(self._joint_values, self._ee_link)
        items = [
            (f"{robot.name} · {joint.name}", result.joint_frames[joint.name])
            for joint in robot.joints
            if joint.name in result.joint_frames
        ]
        if not items:
            return 0
        dialog = self._ensure_tool_dialog()
        return dialog.add_poses(items, visible=False)

    def _on_visuals_toggled(self, enabled: bool) -> None:
        self._show_visuals = bool(enabled)
        self._scene.set_show_visuals(self._show_visuals)
        self._refresh_robot()

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
        self._scene.set_robot(None)
        self._scene.fit_view()
        self._flash_status("已移除机器人模型")

    # ------------------------------------------------------------------
    # 向量
    # ------------------------------------------------------------------

    def _on_vectors_changed(self, vectors: list) -> None:
        was_empty = not self._vectors
        self._vectors = list(vectors)
        self._scene.set_vectors(self._vectors)
        if was_empty and self._vectors:
            self._scene.fit_view()
        if not self._vectors:
            self._flash_status("向量已清空")
            return
        visible = sum(1 for vector in self._vectors if vector.visible)
        self._flash_status(f"向量 {visible} / {len(self._vectors)} 显示")

    # ------------------------------------------------------------------
    # 提示
    # ------------------------------------------------------------------

    def _flash_status(self, text: str) -> None:
        self._status_hint.setText(text)
        self._status_timer.start(3000)

    def _reset_status(self) -> None:
        self._status_hint.setText(DEFAULT_STATUS)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_robot_dialog()
        self._close_tool_dialog()
        self._close_calc_dialog()
        super().closeEvent(event)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "PoseView 使用说明",
            "<b>输入</b><br>"
            "· 点击右上角“位姿 · 向量”打开合并面板，“位姿”标签页可切换齐次矩阵 / 位置 + 四元数 / 位置 + 欧拉角 / 位置 + 旋转向量<br>"
            "· 齐次矩阵：支持 4x4、3x4（旋转 + 平移）与 3x3（仅旋转）<br>"
            "· 位置 + 四元数：每帧 7 个数 <code>x y z qw qx qy qz</code>，四元数会自动归一化<br>"
            "· 位置 + 欧拉角：每帧 6 个数 <code>x y z roll pitch yaw</code>，角度单位为度<br>"
            "· 位置 + 旋转向量：每帧 6 个数 <code>x y z rx ry rz</code>，单位为弧度<br>"
            "· 数字之间可用空格、逗号、分号或方括号分隔<br>"
            "· 空行或 <code>---</code> 分隔多帧，一次可添加多个位姿<br>"
            "· 4x4 最后一行须为 <code>0 0 0 1</code><br><br>"
            "<b>位姿标签页</b><br>"
            "· 位姿列表复选框控制显隐，轨迹按列表顺序连接可见位姿<br>"
            "· “姿态解算”显示位置、RPY、四元数、轴角与旋转向量，可复制<br>"
            "· “相对位姿”选择坐标系 A 与 B，计算 B 在 A 下的 4x4、位置、RPY 与四元数<br>"
            "· 交换按钮可反向计算，复制按钮导出矩阵与姿态结果<br><br>"
            "<b>约定</b><br>"
            "· 右手坐标系，Z 轴向上；矩阵列向量为位姿的 X / Y / Z 轴<br>"
            "· 欧拉角为 ZYX：先绕 Z 偏航（yaw），再绕 Y 俯仰（pitch），最后绕 X 横滚（roll）<br>"
            "· 四元数按 (w, x, y, z) 显示<br><br>"
            "<b>向量标签页</b><br>"
            "· 用“起点 + 方向”或“起点 + 终点”添加，每行 6 个数<br>"
            "· 向量以箭头绘制，起点用圆点标记；列表复选框控制显隐<br>"
            "· “夹角计算”显示夹角、cos θ、点积、模长、叉积与投影，叉积可加入场景<br><br>"
            "<b>计算工具</b><br>"
            "· 点击右上角“计算”打开，包含点位变换、位姿测量、变换链、旋转 / 四元数、数据 / 轨迹<br>"
            "· 点位变换：点按 <code>T·p</code>、向量按 <code>R·v</code> 计算，支持 T⁻¹，可加入场景标注<br>"
            "· 位姿测量：选择 A / B，显示位置差、距离、姿态夹角与 A 坐标系下的转轴<br>"
            "· 变换链：勾选位姿按顺序相乘，支持反向，显示 det、正交误差、迹，可加入为位姿<br>"
            "· 旋转 / 四元数：轴角与旋转向量、四元数乘法 / 共轭、slerp 插值并加入场景<br>"
            "· 数据 / 轨迹：CSV / JSON 导入导出，总路程、总转角、首末位移与分段表<br><br>"
            "<b>机器人 / URDF</b><br>"
            "· 点击右上角“URDF”加载机器人，显示关节骨架、外观与末端坐标系<br>"
            "· 加载时会把各关节坐标系作为位姿加入位姿列表，名称形如 <code>机器人名 · 关节名</code><br>"
            "· 外观支持 box / cylinder / sphere 与 STL / OBJ mesh，颜色取自 URDF material；面板中“外观”复选框可整体开关<br>"
            "· 三维视图右上角“关节”打开关节控制：滑条或数值框驱动正运动学，末端位姿实时更新，可勾选“锁”固定关节<br>"
            "· 点击场景中的连杆或关节可选中高亮，状态栏显示关节角度与限位<br>"
            "· IK 求解：输入目标 x y z roll pitch yaw，或取当前末端作为目标，设置位置 / 姿态权重后点“求解 IK”<br>"
            "· “取当前末端”可校验外部 IK 结果，状态栏显示迭代次数、位置误差与姿态误差<br>"
            "· 支持 revolute / continuous / prismatic / fixed 关节；mimic 关节按 multiplier / offset 跟随源关节，不能单独拖动或锁定<br>"
            "· 外观三角面较多（超过 6000）时默认关闭，避免拖动卡顿；交互期间会自动临时隐藏外观，停下后恢复<br>"
            "· mesh 支持 STL 与 OBJ（DAE 会跳过并提示）<br>"
            "· 取消“位姿”开关可只观察机器人，不受位姿列表干扰<br><br>"
            "<b>操作</b><br>"
            "· 左键拖动旋转，右键拖动平移，滚轮缩放，双击复位<br>"
            "· 点击三维场景中的位姿原点会打开合并面板并切到“位姿”标签页、选中对应位姿<br>"
            "· 工具栏“测量”进入测量模式：点击地面取点，两点测距、三点测角，<code>Esc</code> 清除<br>"
            "· 工具栏“截图”导出当前三维视图<br>"
            "· <code>Ctrl+Enter</code> 打开“位姿 · 向量”面板，<code>Delete</code> 删除面板中选中的位姿",
        )
