"""左侧下部姿态解算区。"""

from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget

from .data_tree import PoseEntry
from .widgets import PoseValuePanel


class SolvePanel(QWidget):
    """展示当前选中位姿或机器人关节坐标系的姿态解算结果。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[PoseEntry] = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        self._value_panel = PoseValuePanel()
        card_layout.addWidget(self._value_panel)
        layout.addWidget(card)
        layout.addStretch(1)

    def set_poses(self, entries: list[PoseEntry]) -> None:
        self._entries = list(entries)

    def select_pose(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            entry = self._entries[index]
            self._value_panel.set_pose(entry.pose, entry.name, entry.color)
        else:
            self._value_panel.clear()

