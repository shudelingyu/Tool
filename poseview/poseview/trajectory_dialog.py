"""关节角轨迹仿真对话框：导入文件并逐帧播放机器人运动。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .icons import icon, primary_icon
from .theme import DANGER, SUCCESS, WARNING, mono_font
from .trajectory import (
    JointTrajectory,
    TrajectoryError,
    frame_values,
    load_trajectory,
    resolve_mapping,
    trajectory_joints,
)
from .urdf import UrdfRobot

BASE_FPS = 30.0
MIN_INTERVAL_MS = 16


class TrajectoryDialog(QDialog):
    """关节角文件导入、列映射与轨迹播放。"""

    frame_applied = pyqtSignal(dict)

    def __init__(
        self,
        robot: UrdfRobot,
        values: dict[str, float],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._robot = robot
        self._base_values = dict(values)
        self._trajectory: JointTrajectory | None = None
        self._frame = -1
        self._setting_slider = False
        self._column_mapping: list[int | None] = []
        self._mapping_combos: list[QComboBox] = []
        self._mapping_warnings: list[str] = []
        self._mapping_updating = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        self.setObjectName("TrajectoryDialog")
        self.setWindowTitle("轨迹仿真")
        self.resize(760, 620)
        self.setMinimumSize(640, 560)
        self._build()
        self._update_info()
        self._update_state()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("轨迹仿真")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "导入 .cst / .cvt / .csv / .txt 关节角文件，逐帧播放机器人运动。"
            f"当前机器人 {self._robot.name} · "
            f"{len(trajectory_joints(self._robot))} 个可映射关节"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        path_label = QLabel("轨迹文件")
        path_label.setObjectName("ValueKey")
        path_label.setFixedWidth(64)
        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("PoseInput")
        self._path_edit.setPlaceholderText(
            "关节角文件路径，例如 D:/data/psm1_joint.cst"
        )
        self._path_edit.returnPressed.connect(self._load_from_edit)
        self._path_edit.editingFinished.connect(self._load_from_edit)
        browse = QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.setIcon(icon("file", "#475569", 15))
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(path_label)
        row.addWidget(self._path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self._info = QLabel()
        self._info.setObjectName("CardHint")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        options = QHBoxLayout()
        options.setSpacing(8)
        unit_label = QLabel("角度单位")
        unit_label.setObjectName("ValueKey")
        self._unit_combo = QComboBox()
        self._unit_combo.addItem("弧度 (rad)", "rad")
        self._unit_combo.addItem("角度 (°)", "deg")
        self._unit_combo.currentIndexChanged.connect(self._on_option_changed)
        mapping_label = QLabel("映射预设")
        mapping_label.setObjectName("ValueKey")
        self._mapping_combo = QComboBox()
        self._mapping_combo.addItem("自动匹配", "auto")
        self._mapping_combo.addItem("按关节顺序", "order")
        self._mapping_combo.addItem("自定义", "custom")
        self._mapping_combo.currentIndexChanged.connect(
            self._on_preset_changed
        )
        options.addWidget(unit_label)
        options.addWidget(self._unit_combo)
        options.addWidget(mapping_label)
        options.addWidget(self._mapping_combo)
        options.addStretch(1)
        layout.addLayout(options)

        layout.addWidget(self._build_mapping_card())

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 11)
        card_layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._play_button = QPushButton("播放")
        self._play_button.setObjectName("Primary")
        self._play_button.setIcon(primary_icon("path", 15))
        self._play_button.setCursor(Qt.PointingHandCursor)
        self._play_button.clicked.connect(self._toggle_play)
        self._stop_button = QPushButton("停止")
        self._stop_button.setObjectName("Ghost")
        self._stop_button.setCursor(Qt.PointingHandCursor)
        self._stop_button.clicked.connect(self._stop)
        speed_label = QLabel("速度")
        speed_label.setObjectName("ValueKey")
        self._speed_combo = QComboBox()
        for text, value in (
            ("0.25×", 0.25),
            ("0.5×", 0.5),
            ("1×", 1.0),
            ("2×", 2.0),
            ("4×", 4.0),
        ):
            self._speed_combo.addItem(text, value)
        self._speed_combo.setCurrentIndex(2)
        self._speed_combo.currentIndexChanged.connect(
            self._on_speed_changed
        )
        self._loop_check = QCheckBox("循环")
        self._loop_check.setCursor(Qt.PointingHandCursor)
        controls.addWidget(self._play_button)
        controls.addWidget(self._stop_button)
        controls.addSpacing(6)
        controls.addWidget(speed_label)
        controls.addWidget(self._speed_combo)
        controls.addWidget(self._loop_check)
        controls.addStretch(1)
        card_layout.addLayout(controls)

        frames = QHBoxLayout()
        frames.setSpacing(8)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setObjectName("JointSlider")
        self._slider.setRange(0, 0)
        self._slider.setCursor(Qt.PointingHandCursor)
        self._slider.sliderPressed.connect(self._pause)
        self._slider.valueChanged.connect(self._on_slider)
        self._frame_label = QLabel("帧 —")
        self._frame_label.setFont(mono_font(10))
        self._frame_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._frame_label.setMinimumWidth(140)
        frames.addWidget(self._slider, 1)
        frames.addWidget(self._frame_label)
        card_layout.addLayout(frames)
        layout.addWidget(card)
        layout.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    def _build_mapping_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 11)
        card_layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("列映射")
        title.setObjectName("SectionTitle")
        hint = QLabel("只控制部分关节时，把其余列设为“不映射”")
        hint.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
        card_layout.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(170)
        scroll.viewport().setObjectName("MappingScrollViewport")
        scroll.viewport().setStyleSheet(
            "QWidget#MappingScrollViewport { background: transparent; }"
        )
        container = QWidget()
        container.setObjectName("MappingContainer")
        container.setStyleSheet(
            "QWidget#MappingContainer { background: transparent; }"
        )
        self._mapping_grid = QGridLayout(container)
        self._mapping_grid.setContentsMargins(0, 0, 2, 0)
        self._mapping_grid.setHorizontalSpacing(8)
        self._mapping_grid.setVerticalSpacing(6)
        self._mapping_grid.setColumnStretch(1, 1)
        self._mapping_grid.setColumnStretch(3, 1)
        scroll.setWidget(container)
        card_layout.addWidget(scroll)
        self._mapping_card = card
        card.setVisible(False)
        return card

    # ------------------------------------------------------------------
    # 列映射
    # ------------------------------------------------------------------

    def _rebuild_mapping_rows(self) -> None:
        trajectory = self._trajectory
        if trajectory is None:
            self._column_mapping = []
            self._mapping_warnings = []
            self._clear_mapping_rows()
            self._mapping_card.setVisible(False)
            return
        mode = self._mapping_combo.currentData()
        if mode == "custom":
            mapping = list(self._column_mapping)
            warnings = list(self._mapping_warnings)
        else:
            mapping, warnings = resolve_mapping(
                trajectory.columns,
                trajectory_joints(self._robot),
                mode,
                trajectory.column_count,
            )
            self._column_mapping = list(mapping)
            self._mapping_warnings = list(warnings)
        self._clear_mapping_rows()
        joints = trajectory_joints(self._robot)
        self._mapping_updating = True
        for column in range(trajectory.column_count):
            label_text = (
                trajectory.columns[column]
                if column < len(trajectory.columns) and trajectory.columns[column]
                else f"列{column + 1}"
            )
            label = QLabel(label_text)
            label.setObjectName("ValueKey")
            label.setToolTip(f"轨迹第 {column + 1} 列")
            combo = QComboBox()
            combo.addItem("不映射", None)
            for index, joint in enumerate(joints):
                combo.addItem(joint.name, index)
            target = mapping[column] if column < len(mapping) else None
            combo_index = combo.findData(target)
            combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _value, position=column: self._on_column_mapping_changed(
                    position
                )
            )
            pair = column // 2
            side = column % 2
            self._mapping_grid.addWidget(label, pair, side * 2)
            self._mapping_grid.addWidget(combo, pair, side * 2 + 1)
            self._mapping_combos.append(combo)
        self._mapping_updating = False
        self._mapping_card.setVisible(True)
        self._update_info()

    def _clear_mapping_rows(self) -> None:
        self._mapping_combos.clear()
        while self._mapping_grid.count():
            item = self._mapping_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_preset_changed(self) -> None:
        if self._trajectory is None:
            return
        if self._mapping_combo.currentData() == "custom":
            self._mapping_warnings = []
            self._update_info()
            return
        self._pause()
        self._rebuild_mapping_rows()
        if self._frame >= 0:
            self._apply_frame(self._frame)

    def _on_column_mapping_changed(self, position: int) -> None:
        if self._mapping_updating or self._trajectory is None:
            return
        if not (0 <= position < len(self._mapping_combos)):
            return
        combo = self._mapping_combos[position]
        index = combo.currentData()
        self._mapping_updating = True
        if index is not None:
            for other, other_combo in enumerate(self._mapping_combos):
                if other == position or other_combo.currentData() != index:
                    continue
                other_combo.setCurrentIndex(0)
                if other < len(self._column_mapping):
                    self._column_mapping[other] = None
        self._mapping_updating = False
        if position < len(self._column_mapping):
            self._column_mapping[position] = index
        self._mapping_warnings = []
        self._set_preset_custom()
        self._pause()
        self._update_info()
        if self._frame >= 0:
            self._apply_frame(self._frame)

    def _set_preset_custom(self) -> None:
        if self._mapping_combo.currentData() == "custom":
            return
        blocked = self._mapping_combo.blockSignals(True)
        index = self._mapping_combo.findData("custom")
        if index >= 0:
            self._mapping_combo.setCurrentIndex(index)
        self._mapping_combo.blockSignals(blocked)

    # ------------------------------------------------------------------
    # 导入
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        start = ""
        if self._path_edit.text().strip():
            start = str(Path(self._path_edit.text().strip()).parent)
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择关节角轨迹文件",
            start,
            "关节角文件 (*.cst *.cvt *.csv *.txt);;所有文件 (*.*)",
        )
        if path:
            self._path_edit.setText(path)
            self._load(path)

    def _load_from_edit(self) -> None:
        path = self._path_edit.text().strip()
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        self._pause()
        try:
            trajectory = load_trajectory(path)
        except TrajectoryError as exc:
            self._trajectory = None
            self._frame = -1
            self._column_mapping = []
            self._mapping_warnings = []
            self._clear_mapping_rows()
            self._mapping_card.setVisible(False)
            self._slider.setRange(0, 0)
            self._info.setText(f"加载失败：{exc}")
            self._info.setStyleSheet(f"color: {DANGER};")
            self._update_state()
            return
        self._trajectory = trajectory
        self._frame = -1
        self._column_mapping = []
        self._mapping_warnings = []
        auto_index = self._mapping_combo.findData("auto")
        blocked = self._mapping_combo.blockSignals(True)
        self._mapping_combo.setCurrentIndex(max(0, auto_index))
        self._mapping_combo.blockSignals(blocked)
        self._slider.blockSignals(True)
        self._slider.setRange(0, max(0, trajectory.frame_count - 1))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._rebuild_mapping_rows()
        self._update_state()
        self._apply_frame(0)

    def _update_info(self) -> None:
        trajectory = self._trajectory
        if trajectory is None:
            self._info.setText("尚未导入轨迹文件")
            self._info.setStyleSheet("color: #64748B;")
            self._info.setToolTip("")
            return
        unmapped = sum(
            1 for index in self._column_mapping if index is None
        )
        text = (
            f"{Path(trajectory.path).name} · {trajectory.frame_count} 帧 · "
            f"{trajectory.column_count} 列关节角"
        )
        if unmapped:
            text += f" · {unmapped} 列不映射（保持当前角度）"
        warnings = trajectory.warnings + self._mapping_warnings
        if warnings:
            text += f"\n提示：{warnings[0]}"
            if len(warnings) > 1:
                text += f"（共 {len(warnings)} 条）"
        self._info.setText(text)
        self._info.setStyleSheet(
            f"color: {WARNING};" if warnings else f"color: {SUCCESS};"
        )
        self._info.setToolTip("\n".join(warnings))

    def _mapping(self) -> tuple[list[int | None], list[str]]:
        if self._trajectory is None:
            return [], []
        return list(self._column_mapping), list(self._mapping_warnings)

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------

    def _interval(self) -> int:
        speed = float(self._speed_combo.currentData() or 1.0)
        return max(MIN_INTERVAL_MS, round(1000.0 / (BASE_FPS * speed)))

    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._pause()
        else:
            self._play()

    def _play(self) -> None:
        trajectory = self._trajectory
        if trajectory is None or trajectory.frame_count < 2:
            return
        if self._frame >= trajectory.frame_count - 1:
            self._apply_frame(0)
        self._timer.start(self._interval())
        self._play_button.setText("暂停")

    def _pause(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._play_button.setText("播放")

    def _stop(self) -> None:
        self._pause()
        if self._trajectory is not None:
            self._apply_frame(0)

    def _advance(self) -> None:
        trajectory = self._trajectory
        if trajectory is None:
            self._pause()
            return
        next_frame = self._frame + 1
        if next_frame >= trajectory.frame_count:
            if self._loop_check.isChecked():
                next_frame = 0
            else:
                self._apply_frame(trajectory.frame_count - 1)
                self._pause()
                return
        self._apply_frame(next_frame)

    def _apply_frame(self, index: int) -> None:
        trajectory = self._trajectory
        if trajectory is None or not trajectory.frames:
            return
        index = max(0, min(index, trajectory.frame_count - 1))
        self._frame = index
        mapping, _warnings = self._mapping()
        values = frame_values(
            self._robot,
            trajectory.frames[index],
            mapping,
            self._base_values,
            self._unit_combo.currentData() == "deg",
        )
        self._setting_slider = True
        self._slider.blockSignals(True)
        self._slider.setValue(index)
        self._slider.blockSignals(False)
        self._setting_slider = False
        self._frame_label.setText(
            f"帧 {index + 1} / {trajectory.frame_count}"
        )
        self.frame_applied.emit(values)

    def _on_slider(self, value: int) -> None:
        if self._setting_slider or self._trajectory is None:
            return
        self._pause()
        self._apply_frame(value)

    def _on_option_changed(self) -> None:
        if self._trajectory is None:
            self._update_state()
            return
        self._pause()
        if self._frame >= 0:
            self._apply_frame(self._frame)

    def _on_speed_changed(self) -> None:
        if self._timer.isActive():
            self._timer.start(self._interval())

    def _update_state(self) -> None:
        trajectory = self._trajectory
        has_frames = trajectory is not None and trajectory.frame_count > 0
        self._play_button.setEnabled(
            has_frames and trajectory.frame_count > 1
        )
        self._stop_button.setEnabled(has_frames)
        self._slider.setEnabled(has_frames)
        self._unit_combo.setEnabled(has_frames)
        self._mapping_combo.setEnabled(has_frames)
        self._speed_combo.setEnabled(has_frames)
        self._loop_check.setEnabled(has_frames)
        if not has_frames:
            self._frame_label.setText("帧 —")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
