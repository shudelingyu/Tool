"""左侧数据树：位姿 / 向量 / 机器人。"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from .icons import dot_icon, icon
from .math3d import Pose, format_number
from .scene import SceneVector
from .theme import mono_font


@dataclass
class PoseEntry:
    name: str
    color: str
    pose: Pose
    visible: bool = True
    tag: str = ""


class DataTree(QTreeWidget):
    """位姿 / 向量 / 机器人三类数据的树状管理。"""

    pose_selected = pyqtSignal(int)
    vector_selected = pyqtSignal(int)
    robot_selected = pyqtSignal()
    poses_changed = pyqtSignal(list)
    vectors_changed = pyqtSignal(list)
    pose_axis_vector_requested = pyqtSignal(int, str)
    robot_visuals_toggled = pyqtSignal(bool)
    robot_skeleton_toggled = pyqtSignal(bool)
    robot_panel_requested = pyqtSignal()
    robot_joint_requested = pyqtSignal(str)
    robot_joint_value_changed = pyqtSignal(str, int)
    robot_remove_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DataTree")
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemChanged.connect(self._on_item_changed)
        self.currentItemChanged.connect(self._on_current_changed)
        self.itemDoubleClicked.connect(self._on_double_clicked)

        self._poses: list[PoseEntry] = []
        self._vectors: list[SceneVector] = []
        self._updating = False
        self._robot_has_visuals = False
        self._robot_skeleton_visible = True
        self._joint_sliders: dict[str, tuple[QSlider, QLabel]] = {}
        self._joint_rows: dict[str, QTreeWidgetItem] = {}
        self._skeleton_item: QTreeWidgetItem | None = None

        bold = QFont()
        bold.setBold(True)

        self._pose_root = QTreeWidgetItem(["位姿"])
        self._vector_root = QTreeWidgetItem(["向量"])
        self._robot_root = QTreeWidgetItem(["机器人"])
        for root in (self._pose_root, self._vector_root, self._robot_root):
            root.setFlags(Qt.ItemIsEnabled)
            root.setFont(0, bold)
        self._pose_root.setIcon(0, icon("axis", "#475569", 14))
        self._vector_root.setIcon(0, icon("vector", "#475569", 14))
        self._robot_root.setIcon(0, icon("robot", "#475569", 14))
        self.addTopLevelItem(self._pose_root)
        self.addTopLevelItem(self._vector_root)
        self.addTopLevelItem(self._robot_root)
        for root in (self._pose_root, self._vector_root, self._robot_root):
            root.setExpanded(True)

        self._fill_empty(self._pose_root, "暂无位姿")
        self._fill_empty(self._vector_root, "暂无向量")
        self._fill_empty(self._robot_root, "未加载机器人")

    # ------------------------------------------------------------------
    # 数据更新
    # ------------------------------------------------------------------

    def set_poses(self, entries: list[PoseEntry], select: int | None = None) -> None:
        self._poses = list(entries)
        self._pose_root.setText(
            0, f"位姿（{len(self._poses)}）" if self._poses else "位姿"
        )
        self._updating = True
        self._pose_root.takeChildren()
        if not self._poses:
            self._fill_empty(self._pose_root, "暂无位姿")
        for index, entry in enumerate(self._poses):
            x, y, z = entry.pose.values.position
            item = QTreeWidgetItem([entry.name])
            item.setIcon(0, dot_icon(entry.color))
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsEditable
            )
            item.setCheckState(0, Qt.Checked if entry.visible else Qt.Unchecked)
            item.setData(0, Qt.UserRole, ("pose", index))
            item.setToolTip(
                0,
                f"{entry.name}\n"
                f"x {format_number(x, 4)}  y {format_number(y, 4)}  "
                f"z {format_number(z, 4)}",
            )
            self._pose_root.addChild(item)
        self._pose_root.setExpanded(True)
        self._updating = False
        self._restore_selection(self._pose_root, select)

    def set_vectors(
        self, vectors: list[SceneVector], select: int | None = None
    ) -> None:
        self._vectors = list(vectors)
        self._vector_root.setText(
            0, f"向量（{len(self._vectors)}）" if self._vectors else "向量"
        )
        self._updating = True
        self._vector_root.takeChildren()
        if not self._vectors:
            self._fill_empty(self._vector_root, "暂无向量")
        for index, vector in enumerate(self._vectors):
            item = QTreeWidgetItem([vector.name])
            item.setIcon(0, dot_icon(vector.color))
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsEditable
            )
            item.setCheckState(0, Qt.Checked if vector.visible else Qt.Unchecked)
            item.setData(0, Qt.UserRole, ("vector", index))
            item.setToolTip(0, self._vector_tooltip(vector))
            self._vector_root.addChild(item)
        self._vector_root.setExpanded(True)
        self._updating = False
        self._restore_selection(self._vector_root, select)

    def set_robot(
        self,
        name: str,
        has_visuals: bool,
        visuals_visible: bool,
        joints: list[tuple[str, str, str, int, bool]] | None = None,
        skeleton_visible: bool = True,
    ) -> None:
        self._robot_has_visuals = has_visuals
        self._robot_skeleton_visible = bool(skeleton_visible)
        self._robot_root.setText(0, "机器人（1）")
        self._updating = True
        self._robot_root.takeChildren()
        self._joint_sliders.clear()
        self._joint_rows.clear()
        item = QTreeWidgetItem([name])
        item.setIcon(0, icon("robot", "#2563EB", 14))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if has_visuals:
            flags |= Qt.ItemIsUserCheckable
        item.setFlags(flags)
        if has_visuals:
            item.setCheckState(
                0, Qt.Checked if visuals_visible else Qt.Unchecked
            )
            item.setToolTip(
                0,
                "勾选显示 / 隐藏 URDF 外观；子项可切换骨架坐标系；双击打开关节控制",
            )
        else:
            item.setToolTip(0, "该机器人没有可绘制外观；双击打开关节控制")
        item.setData(0, Qt.UserRole, ("robot", 0))
        skeleton_item = QTreeWidgetItem(["骨架坐标系"])
        skeleton_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        )
        skeleton_item.setCheckState(
            0, Qt.Checked if self._robot_skeleton_visible else Qt.Unchecked
        )
        skeleton_item.setData(0, Qt.UserRole, ("skeleton", 0))
        skeleton_item.setIcon(0, icon("axis", "#94A3B8", 12))
        skeleton_item.setToolTip(
            0, "显示 / 隐藏骨架、关节轴与各连杆坐标系（外观单独控制）"
        )
        item.addChild(skeleton_item)
        self._skeleton_item = skeleton_item
        joint_items = []
        for joint_name, value_text, tooltip, position, enabled in joints or []:
            child = QTreeWidgetItem([""])
            child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            child.setData(0, Qt.UserRole, ("joint", joint_name))
            child.setToolTip(0, tooltip)
            child.setSizeHint(0, QSize(0, 28))
            item.addChild(child)
            self._joint_rows[joint_name] = child
            joint_items.append(
                (child, joint_name, value_text, tooltip, position, enabled)
            )
        self._robot_root.addChild(item)
        for child, joint_name, value_text, tooltip, position, enabled in joint_items:
            self.setItemWidget(
                child,
                0,
                self._build_joint_row(
                    joint_name, value_text, tooltip, position, enabled
                ),
            )
        item.setExpanded(True)
        self._robot_root.setExpanded(True)
        self._updating = False
        self.setCurrentItem(item)

    def set_robot_skeleton_visible(self, visible: bool) -> None:
        self._robot_skeleton_visible = bool(visible)
        if self._skeleton_item is None:
            return
        self._updating = True
        self._skeleton_item.setCheckState(
            0, Qt.Checked if visible else Qt.Unchecked
        )
        self._updating = False

    def _build_joint_row(
        self,
        joint_name: str,
        value_text: str,
        tooltip: str,
        position: int,
        enabled: bool,
    ) -> QWidget:
        row = QWidget()
        row.setObjectName("JointRow")
        row.setStyleSheet("QWidget#JointRow { background: transparent; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 2, 1)
        layout.setSpacing(5)

        label = QLabel(joint_name)
        label.setStyleSheet("color: #475569;")
        label.setFixedWidth(76)
        label.setToolTip(tooltip)

        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("JointSlider")
        slider.setRange(0, 1000)
        slider.setValue(position)
        slider.setEnabled(enabled)
        slider.setCursor(Qt.PointingHandCursor)
        slider.setToolTip(tooltip)
        slider.valueChanged.connect(
            lambda value, name=joint_name: self._on_joint_slider(name, value)
        )

        value_label = QLabel(value_text)
        value_label.setFont(mono_font(9.5))
        value_label.setFixedWidth(56)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setToolTip(tooltip)

        open_button = QToolButton()
        open_button.setObjectName("IconButton")
        open_button.setIcon(icon("robot", "#94A3B8", 13))
        open_button.setFixedSize(20, 20)
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setToolTip("打开关节控制并定位该关节")
        open_button.clicked.connect(
            lambda: self.robot_joint_requested.emit(joint_name)
        )

        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        layout.addWidget(open_button)
        self._joint_sliders[joint_name] = (slider, value_label)
        return row

    def _on_joint_slider(self, name: str, value: int) -> None:
        if self._updating:
            return
        self.robot_joint_value_changed.emit(name, value)

    def update_robot_joints(
        self, joints: list[tuple[str, str, str, int, bool]]
    ) -> None:
        """关节运动时原地刷新关节列表的数值与滑条，不重建树。"""
        self._updating = True
        for joint_name, value_text, tooltip, position, enabled in joints:
            child = self._joint_rows.get(joint_name)
            if child is None:
                continue
            child.setToolTip(0, tooltip)
            controls = self._joint_sliders.get(joint_name)
            if controls is None:
                continue
            slider, value_label = controls
            slider.blockSignals(True)
            slider.setValue(position)
            slider.blockSignals(False)
            slider.setEnabled(enabled)
            slider.setToolTip(tooltip)
            if value_label.text() != value_text:
                value_label.setText(value_text)
            value_label.setToolTip(tooltip)
        self._updating = False

    @staticmethod
    def _vector_tooltip(vector: SceneVector) -> str:
        return (
            f"{vector.name}\n"
            f"起点 ({format_number(vector.start[0], 3)}, "
            f"{format_number(vector.start[1], 3)}, "
            f"{format_number(vector.start[2], 3)})\n"
            f"终点 ({format_number(vector.end[0], 3)}, "
            f"{format_number(vector.end[1], 3)}, "
            f"{format_number(vector.end[2], 3)})"
        )

    def refresh_vector_tooltips(self, vectors: list[SceneVector]) -> None:
        """轴向量跟随位姿变化后，只刷新提示，不重建树。"""
        self._updating = True
        for index, vector in enumerate(vectors):
            item = self._vector_root.child(index)
            if item is None or item.data(0, Qt.UserRole) is None:
                break
            item.setToolTip(0, self._vector_tooltip(vector))
        self._updating = False

    def refresh_pose_positions(self, entries: list[PoseEntry]) -> None:
        """关节运动后只刷新位姿条目的位置提示，不重建整棵树。"""
        self._updating = True
        for index, entry in enumerate(entries):
            item = self._pose_root.child(index)
            if item is None or item.data(0, Qt.UserRole) is None:
                break
            x, y, z = entry.pose.values.position
            item.setToolTip(
                0,
                f"{entry.name}\n"
                f"x {format_number(x, 4)}  y {format_number(y, 4)}  "
                f"z {format_number(z, 4)}",
            )
        self._updating = False

    def clear_robot(self) -> None:
        self._robot_root.setText(0, "机器人")
        self._joint_sliders.clear()
        self._joint_rows.clear()
        self._skeleton_item = None
        self._robot_skeleton_visible = True
        self._updating = True
        self._robot_root.takeChildren()
        self._fill_empty(self._robot_root, "未加载机器人")
        self._robot_root.setExpanded(True)
        self._updating = False

    def select_pose(self, index: int) -> None:
        self._select_child(self._pose_root, index)

    def select_vector(self, index: int) -> None:
        self._select_child(self._vector_root, index)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _fill_empty(root: QTreeWidgetItem, text: str) -> None:
        item = QTreeWidgetItem([text])
        item.setFlags(Qt.ItemIsEnabled)
        item.setForeground(0, QBrush(QColor("#94A3B8")))
        root.addChild(item)

    def _restore_selection(
        self, root: QTreeWidgetItem, select: int | None
    ) -> None:
        if select is not None:
            self._select_child(root, select)

    def _select_child(self, root: QTreeWidgetItem, index: int) -> None:
        item = root.child(index)
        if item is None or item.data(0, Qt.UserRole) is None:
            return
        if item is self.currentItem():
            self._on_current_changed(item, None)
            return
        self.setCurrentItem(item)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _payload(self, item: QTreeWidgetItem | None):
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    def _on_current_changed(self, current, previous) -> None:
        payload = self._payload(current)
        if payload is None:
            return
        kind, index = payload
        if kind == "pose":
            self.pose_selected.emit(index)
        elif kind == "vector":
            self.vector_selected.emit(index)
        elif kind == "robot":
            self.robot_selected.emit()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating:
            return
        payload = self._payload(item)
        if payload is None:
            return
        kind, index = payload
        if kind == "pose" and 0 <= index < len(self._poses):
            entry = self._poses[index]
            self._apply_name(item, entry, "pose")
            visible = item.checkState(0) == Qt.Checked
            if visible != entry.visible:
                entry.visible = visible
                self.poses_changed.emit(self._poses)
        elif kind == "vector" and 0 <= index < len(self._vectors):
            vector = self._vectors[index]
            self._apply_name(item, vector, "vector")
            visible = item.checkState(0) == Qt.Checked
            if visible != vector.visible:
                vector.visible = visible
                self.vectors_changed.emit(self._vectors)
        elif kind == "robot":
            self.robot_visuals_toggled.emit(
                item.checkState(0) == Qt.Checked
            )
        elif kind == "skeleton":
            visible = item.checkState(0) == Qt.Checked
            self._robot_skeleton_visible = visible
            self.robot_skeleton_toggled.emit(visible)

    def _apply_name(self, item: QTreeWidgetItem, entry, kind: str) -> None:
        name = item.text(0).strip()
        if not name:
            self._updating = True
            item.setText(0, entry.name)
            self._updating = False
            return
        if name != entry.name:
            entry.name = name
            if kind == "pose":
                self.poses_changed.emit(self._poses)
            else:
                self.vectors_changed.emit(self._vectors)

    def _on_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        payload = self._payload(item)
        if payload is None:
            return
        if payload[0] == "robot":
            self.robot_panel_requested.emit()
        elif payload[0] == "joint":
            self.robot_joint_requested.emit(payload[1])

    def _show_menu(self, position) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        payload = self._payload(item)
        menu = QMenu(self)
        if payload is None:
            root = item
            expand_action = menu.addAction("全部展开")
            collapse_action = menu.addAction("全部收起")
            action = menu.exec_(self.viewport().mapToGlobal(position))
            if action == expand_action:
                root.setExpanded(True)
            elif action == collapse_action:
                root.setExpanded(False)
            return
        kind, index = payload
        if kind == "robot":
            panel_action = menu.addAction("关节控制")
            menu.addSeparator()
            if self._robot_has_visuals:
                visual_action = menu.addAction(
                    "隐藏外观"
                    if item.checkState(0) == Qt.Checked
                    else "显示外观"
                )
            else:
                visual_action = None
            menu.addSeparator()
            remove_action = menu.addAction("移除机器人")
            action = menu.exec_(self.viewport().mapToGlobal(position))
            if action == panel_action:
                self.robot_panel_requested.emit()
            elif visual_action is not None and action == visual_action:
                state = (
                    Qt.Unchecked
                    if item.checkState(0) == Qt.Checked
                    else Qt.Checked
                )
                item.setCheckState(0, state)
            elif action == remove_action:
                self.robot_remove_requested.emit()
            return
        if kind == "skeleton":
            toggle_action = menu.addAction(
                "隐藏骨架坐标系"
                if item.checkState(0) == Qt.Checked
                else "显示骨架坐标系"
            )
            action = menu.exec_(self.viewport().mapToGlobal(position))
            if action == toggle_action:
                state = (
                    Qt.Unchecked
                    if item.checkState(0) == Qt.Checked
                    else Qt.Checked
                )
                item.setCheckState(0, state)
            return
        if kind == "joint":
            control_action = menu.addAction("关节控制")
            action = menu.exec_(self.viewport().mapToGlobal(position))
            if action == control_action:
                self.robot_joint_requested.emit(index)
            return

        rename_action = menu.addAction("重命名")
        toggle_action = menu.addAction(
            "隐藏" if item.checkState(0) == Qt.Checked else "显示"
        )
        axis_actions = {}
        if kind == "pose":
            axis_menu = menu.addMenu("添加轴向量")
            axis_menu.setToolTip("以该坐标系的位置为起点，添加 X / Y / Z 轴向量")
            for key, label in (("x", "X 轴"), ("y", "Y 轴"), ("z", "Z 轴")):
                axis_actions[axis_menu.addAction(label)] = key
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.viewport().mapToGlobal(position))
        if action == rename_action:
            self.editItem(item, 0)
        elif action == toggle_action:
            state = (
                Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
            )
            item.setCheckState(0, state)
        elif action in axis_actions:
            self.pose_axis_vector_requested.emit(index, axis_actions[action])
        elif action == delete_action:
            self._delete_item(kind, index)

    def _delete_item(self, kind: str, index: int) -> None:
        if kind == "pose":
            if not (0 <= index < len(self._poses)):
                return
            self._poses.pop(index)
            self.set_poses(self._poses, select=min(index, len(self._poses) - 1))
            self.poses_changed.emit(self._poses)
        elif kind == "vector":
            if not (0 <= index < len(self._vectors)):
                return
            self._vectors.pop(index)
            self.set_vectors(
                self._vectors, select=min(index, len(self._vectors) - 1)
            )
            self.vectors_changed.emit(self._vectors)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Delete:
            payload = self._payload(self.currentItem())
            if payload is not None and payload[0] in ("pose", "vector"):
                self._delete_item(payload[0], payload[1])
                return
        super().keyPressEvent(event)
