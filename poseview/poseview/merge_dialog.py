"""URDF 拼接对话框：把附加模型固定到当前机器人上。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .icons import icon, primary_icon
from .math3d import rotation_from_euler
from .theme import DANGER, SUCCESS, WARNING
from .urdf import UrdfError, UrdfRobot, load_urdf, merge_urdf


def _parse_origin(text: str):
    parts = text.replace(",", " ").split()
    if len(parts) != 6:
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    x, y, z, roll, pitch, yaw = values
    rotation = rotation_from_euler(roll, pitch, yaw)
    return [
        [rotation[0][0], rotation[0][1], rotation[0][2], x],
        [rotation[1][0], rotation[1][1], rotation[1][2], y],
        [rotation[2][0], rotation[2][1], rotation[2][2], z],
        [0.0, 0.0, 0.0, 1.0],
    ]


class MergeDialog(QDialog):
    """选择附加 URDF 与安装参数，确认后生成拼接机器人。"""

    def __init__(self, robot: UrdfRobot, parent=None) -> None:
        super().__init__(parent)
        self._robot = robot
        self._attachment: UrdfRobot | None = None
        self.merged_robot: UrdfRobot | None = None
        self.merge_warnings: list[str] = []

        self.setObjectName("MergeDialog")
        self.setWindowTitle("拼接 URDF")
        self.resize(660, 430)
        self.setMinimumWidth(580)
        self._build()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("拼接 URDF")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            f"当前机器人 {self._robot.name} · "
            f"{len(self._robot.link_names)} 个 link · "
            f"{len(self._robot.movable_joints)} 个可动关节\n"
            "把附加 URDF 的根 link 通过固定关节接到当前机器人的指定 link。"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        path_label = QLabel("附加 URDF")
        path_label.setObjectName("ValueKey")
        path_label.setFixedWidth(76)
        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("PoseInput")
        self._path_edit.setPlaceholderText("URDF 文件路径，例如 D:/robot/gripper.urdf")
        self._path_edit.editingFinished.connect(self._load_attachment)
        browse = QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.setIcon(icon("file", "#475569", 15))
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(path_label)
        row.addWidget(self._path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("安装 link")
        label.setObjectName("ValueKey")
        label.setFixedWidth(76)
        self._mount_combo = QComboBox()
        self._mount_combo.addItems(self._robot.link_names)
        tooltip = "当前机器人上用于安装附加模型的 link"
        self._mount_combo.setToolTip(tooltip)
        row.addWidget(label)
        row.addWidget(self._mount_combo, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("接入根 link")
        label.setObjectName("ValueKey")
        label.setFixedWidth(76)
        self._root_label = QLabel("—")
        self._root_label.setObjectName("ValueNum")
        self._root_label.setToolTip("附加 URDF 的根 link，将作为装配关节的子 link")
        row.addWidget(label)
        row.addWidget(self._root_label, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("名称前缀")
        label.setObjectName("ValueKey")
        label.setFixedWidth(76)
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setObjectName("PoseInput")
        self._prefix_edit.setPlaceholderText("留空则按需自动加前缀，处理 link / joint 重名")
        row.addWidget(label)
        row.addWidget(self._prefix_edit, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("装配关节")
        label.setObjectName("ValueKey")
        label.setFixedWidth(76)
        self._joint_edit = QLineEdit("mount")
        self._joint_edit.setObjectName("PoseInput")
        self._joint_edit.setPlaceholderText("固定关节名称")
        row.addWidget(label)
        row.addWidget(self._joint_edit, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("安装位姿")
        label.setObjectName("ValueKey")
        label.setFixedWidth(76)
        self._origin_edit = QLineEdit("0 0 0 0 0 0")
        self._origin_edit.setObjectName("PoseInput")
        self._origin_edit.setPlaceholderText("x y z roll pitch yaw（角度制）")
        row.addWidget(label)
        row.addWidget(self._origin_edit, 1)
        layout.addLayout(row)

        self._hint = QLabel("选择附加 URDF 后显示预览")
        self._hint.setObjectName("CardHint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self._merge_button = QPushButton("拼接")
        self._merge_button.setObjectName("Primary")
        self._merge_button.setIcon(primary_icon("link", 15))
        self._merge_button.setCursor(Qt.PointingHandCursor)
        self._merge_button.clicked.connect(self._accept)
        self._merge_button.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(self._merge_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    # 附加模型
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择附加 URDF",
            "",
            "URDF 文件 (*.urdf *.xml);;所有文件 (*.*)",
        )
        if path:
            self._path_edit.setText(path)
            self._load_attachment()

    def _load_attachment(self) -> None:
        path = self._path_edit.text().strip()
        self._attachment = None
        self.merged_robot = None
        self._merge_button.setEnabled(False)
        self._root_label.setText("—")
        if not path:
            self._set_hint("请选择附加 URDF", DANGER)
            return
        if not Path(path).is_file():
            self._set_hint("附加 URDF 文件不存在", DANGER)
            return
        try:
            robot = load_urdf(path)
        except UrdfError as exc:
            self._set_hint(f"附加 URDF 加载失败：{exc}", DANGER)
            return
        self._attachment = robot
        self._root_label.setText(robot.root_link)
        details = (
            f"附加模型 {robot.name} · {len(robot.link_names)} 个 link · "
            f"{len(robot.movable_joints)} 个可动关节 · 根 link {robot.root_link}"
        )
        if robot.warnings:
            details += f"\n{'；'.join(robot.warnings[:2])}"
        color = SUCCESS if not robot.warnings else WARNING
        self._set_hint(details, color)
        self._merge_button.setEnabled(True)

    # ------------------------------------------------------------------
    # 确认
    # ------------------------------------------------------------------

    def _accept(self) -> None:
        if self._attachment is None:
            self._set_hint("请先加载附加 URDF", DANGER)
            return
        mount_link = self._mount_combo.currentText().strip()
        if not mount_link:
            self._set_hint("请选择安装 link", DANGER)
            return
        origin = _parse_origin(self._origin_edit.text())
        if origin is None:
            self._set_hint("安装位姿需要 6 个数：x y z roll pitch yaw", DANGER)
            return
        try:
            merged, warnings = merge_urdf(
                self._robot,
                self._attachment,
                mount_link,
                self._joint_edit.text().strip() or "mount",
                origin,
                self._prefix_edit.text(),
            )
        except UrdfError as exc:
            self._set_hint(f"拼接失败：{exc}", DANGER)
            return
        self.merged_robot = merged
        self.merge_warnings = warnings
        self.accept()

    def _set_hint(self, text: str, color: str) -> None:
        self._hint.setText(text)
        self._hint.setStyleSheet(f"color: {color};")
