"""位姿与向量合并面板。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from .pose_dialog import PosePanel
from .vector_dialog import VectorPanel


class PoseVectorDialog(QDialog):
    """用“位姿 / 向量”两个标签页统一管理相关工具。"""

    poses_changed = pyqtSignal(list)
    selection_changed = pyqtSignal(int)
    vectors_changed = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PoseVectorDialog")
        self.setWindowTitle("位姿与向量")
        self.resize(1080, 860)
        self.setMinimumSize(940, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("位姿与向量")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "“位姿”标签页：输入与列表、姿态解算、相对位姿；\n"
            "“向量”标签页：带起点向量、夹角、单位向量、叉积与投影。"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("PoseVectorTabs")
        self.pose_panel = PosePanel()
        self.vector_panel = VectorPanel()
        self._tabs.addTab(self.pose_panel, "位姿")
        self._tabs.addTab(self.vector_panel, "向量")
        layout.addWidget(self._tabs, 1)

        self.pose_panel.poses_changed.connect(self.poses_changed)
        self.pose_panel.selection_changed.connect(self.selection_changed)
        self.vector_panel.vectors_changed.connect(self.vectors_changed)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def set_tab(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def current_tab(self) -> int:
        return self._tabs.currentIndex()

    def add_pose(
        self, matrix: list[list[float]], name: str = "", visible: bool = True
    ) -> None:
        self.pose_panel.add_pose(matrix, name, visible)

    def add_poses(self, items: list, visible: bool = True) -> int:
        return self.pose_panel.add_poses(items, visible)

    def select_row(self, index: int) -> None:
        self.pose_panel.select_row(index)

    def add_vector(self, start, direction, name: str = "") -> str:
        return self.vector_panel.add_vector(start, direction, name)
