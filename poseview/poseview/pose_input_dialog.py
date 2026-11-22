"""位姿输入对话框。"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from .icons import primary_icon
from .math3d import MatrixParseError, Pose, parse_poses
from .theme import DANGER, MUTED, SUCCESS, mono_font

INPUT_MODES = (
    ("matrix", "齐次矩阵"),
    ("quat", "位置 + 四元数"),
    ("euler", "位置 + 欧拉角"),
    ("rotvec", "位置 + 旋转向量"),
)

MODE_HINTS = {
    "matrix": "支持 3x3 / 3x4 / 4x4；空行或 --- 分隔多个矩阵",
    "quat": "每帧 7 个数：x y z qw qx qy qz；空行或 --- 分隔多帧",
    "euler": "每帧 6 个数：x y z roll pitch yaw（度）；空行或 --- 分隔多帧",
    "rotvec": "每帧 6 个数：x y z rx ry rz（弧度）；空行或 --- 分隔多帧",
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
    "rotvec": (
        "粘贴位置 + 旋转向量，每帧 6 个数：\n"
        "x y z rx ry rz（rad）\n"
        "0 0 0   0 0 1.5708"
    ),
}


class PoseInputDialog(QDialog):
    """录入一组位姿，确认后由主窗口加入位姿树。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PoseInputDialog")
        self.setWindowTitle("添加位姿")
        self.resize(620, 640)
        self.setMinimumSize(480, 520)
        self._poses: list[Pose] = []
        self._mode = "matrix"
        self._default_hint = MODE_HINTS["matrix"]
        self._build()

    @property
    def poses(self) -> list[Pose]:
        return list(self._poses)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("添加位姿")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel("统一转换为 4x4 齐次矩阵后加入位姿树")
        hint.setObjectName("DialogHint")
        layout.addWidget(hint)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._mode_group = QButtonGroup(self)
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
        self._editor.setMinimumHeight(220)
        self._editor.setTabChangesFocus(True)
        self._editor.setPlaceholderText(PLACEHOLDERS["matrix"])
        card_layout.addWidget(self._editor, 1)

        self._parse_hint = QLabel(self._default_hint)
        self._parse_hint.setObjectName("CardHint")
        self._parse_hint.setWordWrap(True)
        card_layout.addWidget(self._parse_hint)
        layout.addWidget(card, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        add = QPushButton("添加位姿")
        add.setObjectName("Primary")
        add.setIcon(primary_icon("plus", 15))
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        layout.addLayout(buttons)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._accept)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._editor.setFocus()

    def _set_mode(self, key: str) -> None:
        if key not in PLACEHOLDERS:
            return
        button = self._mode_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._mode = key
        self._editor.setPlaceholderText(PLACEHOLDERS[key])
        self._default_hint = MODE_HINTS[key]
        self._show_hint(self._default_hint, MUTED)

    def _accept(self) -> None:
        try:
            poses = parse_poses(self._editor.toPlainText(), mode=self._mode)
        except MatrixParseError as exc:
            self._show_hint(str(exc), DANGER)
            return
        if not poses:
            self._show_hint("没有可添加的位姿", DANGER)
            return
        self._poses = poses
        self.accept()

    def _show_hint(self, text: str, color: str) -> None:
        self._parse_hint.setText(text)
        self._parse_hint.setStyleSheet(f"color: {color};")


__all__ = ["PoseInputDialog", "INPUT_MODES", "MODE_HINTS", "PLACEHOLDERS"]
