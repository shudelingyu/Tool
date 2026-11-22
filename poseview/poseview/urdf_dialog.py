"""URDF 加载对话框。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .icons import icon, primary_icon
from .theme import DANGER


class UrdfDialog(QDialog):
    """选择 URDF 文件路径，确认后由主窗口加载。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("UrdfDialog")
        self.setWindowTitle("加载 URDF")
        self.resize(620, 240)
        self.setMinimumWidth(520)
        self._build()

    @property
    def path(self) -> str:
        return self._path_edit.text().strip()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("加载 URDF 机器人")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "选择 .urdf / .xml 文件；加载后机器人显示在左侧“机器人”节点，各关节位姿会加入位姿树"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("PoseInput")
        self._path_edit.setPlaceholderText("URDF 文件路径，例如 D:/robot/arm.urdf")
        self._path_edit.returnPressed.connect(self._accept)
        browse = QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.setIcon(icon("file", "#475569", 15))
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(self._path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self._hint = QLabel("")
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
        load = QPushButton("加载")
        load.setObjectName("Primary")
        load.setIcon(primary_icon("file", 15))
        load.setCursor(Qt.PointingHandCursor)
        load.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(load)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._path_edit.setFocus()

    def _browse(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择 URDF 文件",
            "",
            "URDF 文件 (*.urdf *.xml);;所有文件 (*.*)",
        )
        if path:
            self._path_edit.setText(path)
            self._hint.setText("")

    def _accept(self) -> None:
        path = self.path
        if not path:
            self._show_hint("请输入或选择 URDF 文件路径", DANGER)
            return
        if not Path(path).is_file():
            self._show_hint("文件不存在，请检查路径", DANGER)
            return
        self.accept()

    def _show_hint(self, text: str, color: str) -> None:
        self._hint.setText(text)
        self._hint.setStyleSheet(f"color: {color};")
