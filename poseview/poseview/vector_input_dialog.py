"""向量输入对话框。"""

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
from .math3d import MatrixParseError, parse_vectors
from .theme import DANGER, MUTED, mono_font

INPUT_MODES = (
    ("direction", "起点 + 方向"),
    ("end", "起点 + 终点"),
)

PLACEHOLDERS = {
    "direction": (
        "每行一个向量：起点 x y z + 方向 x y z\n"
        "0 0 0   1 0 0\n"
        "1 0 1   0 0 1"
    ),
    "end": (
        "每行一个向量：起点 x y z + 终点 x y z\n"
        "0 0 0   1 0 0\n"
        "1 0 1   1 0 2"
    ),
}

MODE_HINTS = {
    "direction": "起点处绘制箭头，长度取方向向量的模长；空行或 --- 分隔多个向量",
    "end": "起点处绘制箭头并指向终点；空行或 --- 分隔多个向量",
}


class VectorInputDialog(QDialog):
    """录入一组带起点的向量，确认后由主窗口加入向量树。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("VectorInputDialog")
        self.setWindowTitle("添加向量")
        self.resize(620, 600)
        self.setMinimumSize(480, 480)
        self._vectors: list[tuple] = []
        self._mode = "direction"
        self._default_hint = MODE_HINTS["direction"]
        self._build()

    @property
    def vectors(self) -> list[tuple]:
        return list(self._vectors)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("添加向量")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel("向量以“起点 + 方向”或“起点 + 终点”录入，确认后加入向量树")
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
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
        self._mode_buttons["direction"].setChecked(True)
        card_layout.addLayout(mode_row)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MatrixEditor")
        self._editor.setFont(mono_font(11.5))
        self._editor.setMinimumHeight(200)
        self._editor.setTabChangesFocus(True)
        self._editor.setPlaceholderText(PLACEHOLDERS["direction"])
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
        add = QPushButton("添加向量")
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
            parsed = parse_vectors(self._editor.toPlainText(), self._mode)
        except MatrixParseError as exc:
            self._show_hint(str(exc), DANGER)
            return
        vectors = [
            (start, direction)
            for start, direction in parsed
            if abs(direction[0]) + abs(direction[1]) + abs(direction[2]) > 1e-9
        ]
        if not vectors:
            self._show_hint("没有有效向量（长度为 0 的向量会被忽略）", DANGER)
            return
        self._vectors = vectors
        self.accept()

    def _show_hint(self, text: str, color: str) -> None:
        self._parse_hint.setText(text)
        self._parse_hint.setStyleSheet(f"color: {color};")
