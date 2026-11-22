"""深色三维场景：地面网格、世界坐标轴、位姿坐标轴与轨迹。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt5.QtWidgets import QWidget

from .theme import mono_font

POSE_COLORS = [
    "#22D3EE",
    "#F59E0B",
    "#A78BFA",
    "#34D399",
    "#F472B6",
    "#FBBF24",
    "#38BDF8",
    "#FB7185",
]

VECTOR_COLORS = [
    "#FDE047",
    "#FB7185",
    "#38BDF8",
    "#A3E635",
    "#FB923C",
    "#C084FC",
]

AXIS_COLORS = ("#F87171", "#4ADE80", "#60A5FA")
AXIS_LABELS = ("X", "Y", "Z")

# 三角面超过该数量时，交互（拖动/缩放）期间不绘制外观，避免逐面绘制掉帧。
INTERACTIVE_TRIANGLE_LIMIT = 6000


@dataclass
class ScenePose:
    name: str
    color: str
    position: tuple[float, float, float]
    rotation: list[list[float]]
    visible: bool = True


@dataclass
class SceneVector:
    name: str
    color: str
    start: tuple[float, float, float]
    direction: tuple[float, float, float]
    visible: bool = True
    source: str = ""
    axis: str = ""

    @property
    def end(self) -> tuple[float, float, float]:
        return (
            self.start[0] + self.direction[0],
            self.start[1] + self.direction[1],
            self.start[2] + self.direction[2],
        )


@dataclass
class SceneMarker:
    name: str
    color: str
    position: tuple[float, float, float]


@dataclass
class SceneVisual:
    link: str
    color: str
    alpha: float
    triangles: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ]


@dataclass
class RobotJoint:
    name: str
    type: str
    position: tuple[float, float, float]
    axis: tuple[float, float, float]
    lower: float
    upper: float
    value: float


@dataclass
class SceneFrame:
    position: tuple[float, float, float]
    rotation: list[list[float]]
    name: str = ""


@dataclass
class RobotSkeleton:
    name: str
    bones: list[tuple[tuple[float, float, float], tuple[float, float, float]]]
    joints: list[tuple[float, float, float]]
    end_effector: SceneFrame | None = None
    target: SceneFrame | None = None
    joint_frames: list[SceneFrame] = field(default_factory=list)
    visuals: list[SceneVisual] = field(default_factory=list)
    bone_links: list[str] = field(default_factory=list)
    joints_info: list[RobotJoint] = field(default_factory=list)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(vector):
    length = math.sqrt(_dot(vector, vector))
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _nice_step(value: float) -> float:
    if value <= 1e-9:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10.0 ** exponent
    for multiplier in (1.0, 2.0, 5.0, 10.0):
        candidate = multiplier * base
        if value <= candidate:
            return candidate
    return 10.0 * base


def _point_in_triangle(point, first, second, third) -> bool:
    def side(a, b, c) -> float:
        return (a.x() - c.x()) * (b.y() - c.y()) - (
            b.x() - c.x()
        ) * (a.y() - c.y())

    first_side = side(point, first, second)
    second_side = side(point, second, third)
    third_side = side(point, third, first)
    has_negative = first_side < 0 or second_side < 0 or third_side < 0
    has_positive = first_side > 0 or second_side > 0 or third_side > 0
    return not (has_negative and has_positive)


def _point_segment_distance(point, start, end) -> float:
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return math.hypot(point.x() - start.x(), point.y() - start.y())
    ratio = (
        (point.x() - start.x()) * dx + (point.y() - start.y()) * dy
    ) / length_sq
    ratio = max(0.0, min(1.0, ratio))
    x = start.x() + ratio * dx
    y = start.y() + ratio * dy
    return math.hypot(point.x() - x, point.y() - y)


class _Camera:
    def __init__(self) -> None:
        self.target = [0.0, 0.0, 0.0]
        self.distance = 7.0
        self.yaw = -52.0
        self.pitch = 24.0
        self.fov = 42.0

    def basis(self):
        yaw = math.radians(self.yaw)
        pitch = math.radians(self.pitch)
        offset = (
            math.cos(pitch) * math.cos(yaw),
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
        )
        eye = [self.target[i] + self.distance * offset[i] for i in range(3)]
        forward = (-offset[0], -offset[1], -offset[2])
        right = _normalize(_cross(forward, (0.0, 0.0, 1.0)))
        up = _cross(right, forward)
        return eye, forward, right, up


class _View:
    """一次绘制使用的投影参数。"""

    def __init__(self, camera: _Camera, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self.eye, self.forward, self.right, self.up = camera.basis()
        self.focal = 0.5 * self.height / math.tan(math.radians(camera.fov) / 2.0)
        self.camera = camera

    def project(self, point):
        rel = (
            point[0] - self.eye[0],
            point[1] - self.eye[1],
            point[2] - self.eye[2],
        )
        depth = _dot(rel, self.forward)
        if depth < 0.05:
            return None
        x = _dot(rel, self.right)
        y = _dot(rel, self.up)
        screen = QPointF(
            self.width / 2.0 + self.focal * x / depth,
            self.height / 2.0 - self.focal * y / depth,
        )
        return screen, depth


class PoseScene(QWidget):
    """鼠标可旋转 / 平移 / 缩放的位姿三维视图。"""

    pose_clicked = pyqtSignal(int)
    robot_item_selected = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self._camera = _Camera()
        self._poses: list[ScenePose] = []
        self._vectors: list[SceneVector] = []
        self._markers: list[SceneMarker] = []
        self._robot: RobotSkeleton | None = None
        self._selected = -1
        self._show_grid = True
        self._show_path = True
        self._show_labels = True
        self._show_poses = True
        self._measure_mode = False
        self._measure_points: list[tuple[float, float, float]] = []
        self._show_visuals = True
        self._show_skeleton = True
        self._selected_link = ""
        self._selected_joint = ""
        self._press_pos = None
        self._last_pos = None
        self._drag_button = None
        self._moved = False
        self._visual_triangle_count = 0
        self._interacting = False
        self._quality_timer = QTimer(self)
        self._quality_timer.setSingleShot(True)
        self._quality_timer.timeout.connect(self._restore_quality)

    # ------------------------------------------------------------------
    # 数据与选项
    # ------------------------------------------------------------------

    def set_poses(self, poses: list[ScenePose]) -> None:
        self._poses = poses
        if self._selected >= len(poses):
            self._selected = -1
        self.update()

    def set_vectors(self, vectors: list[SceneVector]) -> None:
        self._vectors = vectors
        self.update()

    def set_markers(self, markers: list[SceneMarker]) -> None:
        self._markers = markers
        self.update()

    def set_measure_mode(self, enabled: bool) -> None:
        self._measure_mode = bool(enabled)
        if not self._measure_mode:
            self._measure_points.clear()
        self.setCursor(Qt.CrossCursor if self._measure_mode else Qt.OpenHandCursor)
        self.update()

    def clear_measurements(self) -> None:
        self._measure_points.clear()
        self.update()

    def set_selected(self, index: int) -> None:
        self._selected = index
        self.update()

    def set_robot(self, robot: RobotSkeleton | None) -> None:
        self._robot = robot
        if robot is None:
            self._selected_link = ""
            self._selected_joint = ""
            self._visual_triangle_count = 0
        else:
            links = {visual.link for visual in robot.visuals}
            links.update(robot.bone_links)
            if self._selected_link and self._selected_link not in links:
                self._selected_link = ""
            joint_names = {joint.name for joint in robot.joints_info}
            if self._selected_joint and self._selected_joint not in joint_names:
                self._selected_joint = ""
            self._visual_triangle_count = sum(
                len(visual.triangles) for visual in robot.visuals
            )
        self.update()

    def visual_triangle_count(self) -> int:
        return self._visual_triangle_count

    def _begin_interaction(self) -> None:
        if self._visual_triangle_count <= INTERACTIVE_TRIANGLE_LIMIT:
            return
        self._interacting = True
        self._quality_timer.start(160)

    def _restore_quality(self) -> None:
        if self._interacting:
            self._interacting = False
            self.update()

    def set_show_visuals(self, enabled: bool) -> None:
        self._show_visuals = bool(enabled)
        self.update()

    def set_show_skeleton(self, enabled: bool) -> None:
        """显示 / 隐藏机器人骨架、关节轴与各连杆坐标系。"""
        self._show_skeleton = bool(enabled)
        self.update()

    def set_show_poses(self, enabled: bool) -> None:
        self._show_poses = bool(enabled)
        self.update()

    def set_show_grid(self, enabled: bool) -> None:
        self._show_grid = bool(enabled)
        self.update()

    def set_show_path(self, enabled: bool) -> None:
        self._show_path = bool(enabled)
        self.update()

    def set_show_labels(self, enabled: bool) -> None:
        self._show_labels = bool(enabled)
        self.update()

    def reset_view(self) -> None:
        self._camera.yaw = -52.0
        self._camera.pitch = 24.0
        self.fit_view()

    def fit_view(self) -> None:
        center, radius = self._fit_geometry()
        self._camera.target = list(center)
        vertical_fov = math.radians(self._camera.fov)
        width = max(1, self.width())
        height = max(1, self.height())
        tan_vertical = math.tan(vertical_fov / 2.0)
        tan_horizontal = tan_vertical * width / height
        half_angle = math.atan(min(tan_vertical, tan_horizontal))
        distance = radius / max(0.05, math.sin(half_angle * 0.94))
        self._camera.distance = max(1.8, distance)
        self.update()

    # ------------------------------------------------------------------
    # 鼠标交互
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press_pos = event.pos()
        self._last_pos = event.pos()
        self._drag_button = event.button()
        self._moved = False
        if event.button() == Qt.LeftButton:
            self.setCursor(
                Qt.CrossCursor if self._measure_mode else Qt.ClosedHandCursor
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_pos is None or self._drag_button is None:
            return
        delta = event.pos() - self._last_pos
        self._last_pos = event.pos()
        if delta.manhattanLength() > 0:
            if (event.pos() - self._press_pos).manhattanLength() > 3:
                self._moved = True
        if event.buttons() & Qt.LeftButton:
            self._camera.yaw -= delta.x() * 0.45
            self._camera.pitch = max(-85.0, min(85.0, self._camera.pitch + delta.y() * 0.4))
            self._begin_interaction()
            self.update()
        elif event.buttons() & (Qt.RightButton | Qt.MiddleButton):
            self._pan(delta.x(), delta.y())
            self._begin_interaction()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.CrossCursor if self._measure_mode else Qt.OpenHandCursor)
        if (
            event.button() == Qt.LeftButton
            and not self._moved
            and self._press_pos is not None
        ):
            if self._measure_mode:
                self._add_measure_point(event.pos())
            else:
                self._pick(event.pos())
        self._last_pos = None
        self._drag_button = None
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self._measure_points:
            self.clear_measurements()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self._measure_mode:
                self.clear_measurements()
            else:
                self.reset_view()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._camera.distance = max(0.08, min(1e6, self._camera.distance * math.exp(-steps * 0.13)))
            self._begin_interaction()
            self.update()
        event.accept()

    def _pan(self, dx: int, dy: int) -> None:
        view = _View(self._camera, self.width(), self.height())
        scale = self._camera.distance / view.focal
        for i in range(3):
            self._camera.target[i] += (-view.right[i] * dx + view.up[i] * dy) * scale

    def _pick(self, pos) -> None:
        if self._pick_robot(pos):
            return
        view = _View(self._camera, self.width(), self.height())
        best = -1
        best_distance = 16.0
        for index, pose in enumerate(self._poses):
            if not pose.visible:
                continue
            projected = view.project(pose.position)
            if projected is None:
                continue
            screen = projected[0]
            distance = math.hypot(screen.x() - pos.x(), screen.y() - pos.y())
            if distance < best_distance:
                best_distance = distance
                best = index
        if best >= 0:
            self.pose_clicked.emit(best)

    def _pick_robot(self, pos) -> bool:
        robot = self._robot
        if robot is None:
            return False
        view = _View(self._camera, self.width(), self.height())

        best_joint = ""
        best_distance = 12.0
        for joint in robot.joints_info:
            projected = view.project(joint.position)
            if projected is None:
                continue
            screen = projected[0]
            distance = math.hypot(screen.x() - pos.x(), screen.y() - pos.y())
            if distance < best_distance:
                best_distance = distance
                best_joint = joint.name
        if best_joint:
            self._select_robot_item("joint", best_joint)
            return True

        if self._show_visuals and robot.visuals:
            best_depth = float("inf")
            best_link = ""
            for visual in robot.visuals:
                for triangle in visual.triangles:
                    projected = [
                        view.project(vertex) for vertex in triangle
                    ]
                    if any(item is None for item in projected):
                        continue
                    points = [item[0] for item in projected]
                    if not _point_in_triangle(
                        pos, points[0], points[1], points[2]
                    ):
                        continue
                    depth = sum(item[1] for item in projected) / 3.0
                    if depth < best_depth:
                        best_depth = depth
                        best_link = visual.link
            if best_link:
                self._select_robot_item("link", best_link)
                return True

        best_link = ""
        best_distance = 10.0
        for index, (start, end) in enumerate(robot.bones):
            first = view.project(start)
            second = view.project(end)
            if first is None or second is None:
                continue
            distance = _point_segment_distance(
                pos, first[0], second[0]
            )
            if (
                distance < best_distance
                and index < len(robot.bone_links)
            ):
                best_distance = distance
                best_link = robot.bone_links[index]
        if best_link:
            self._select_robot_item("link", best_link)
            return True
        return False

    def _select_robot_item(self, kind: str, name: str) -> None:
        if kind == "joint":
            self._selected_joint = name
            self._selected_link = ""
        else:
            self._selected_link = name
            self._selected_joint = ""
        self.robot_item_selected.emit(kind, name)
        self.update()

    def _ground_point(self, pos):
        view = _View(self._camera, self.width(), self.height())
        x = (pos.x() - self.width() / 2.0) / view.focal
        y = -(pos.y() - self.height() / 2.0) / view.focal
        direction = _normalize(
            (
                view.forward[0] + view.right[0] * x + view.up[0] * y,
                view.forward[1] + view.right[1] * x + view.up[1] * y,
                view.forward[2] + view.right[2] * x + view.up[2] * y,
            )
        )
        if abs(direction[2]) < 1e-6:
            return None
        distance = -view.eye[2] / direction[2]
        if distance <= 0.05:
            return None
        return tuple(view.eye[i] + direction[i] * distance for i in range(3))

    def _add_measure_point(self, pos) -> None:
        point = self._ground_point(pos)
        if point is None:
            return
        if len(self._measure_points) >= 3:
            self._measure_points.clear()
        self._measure_points.append(point)
        self.update()

    # ------------------------------------------------------------------
    # 场景几何
    # ------------------------------------------------------------------

    def _fit_geometry(self):
        points: list[tuple[float, float, float]] = []
        if self._show_poses:
            poses = [pose for pose in self._poses if pose.visible] or self._poses
            points.extend(pose.position for pose in poses)
        for vector in self._vectors:
            if vector.visible:
                points.append(vector.start)
                points.append(vector.end)
        points.extend(marker.position for marker in self._markers)
        points.extend(self._measure_points)
        if self._robot is not None:
            if self._show_skeleton:
                for start, end in self._robot.bones:
                    points.append(start)
                    points.append(end)
                points.extend(self._robot.joints)
                if self._robot.end_effector is not None:
                    points.append(self._robot.end_effector.position)
                if self._robot.target is not None:
                    points.append(self._robot.target.position)
            if self._show_visuals:
                for visual in self._robot.visuals:
                    for triangle in visual.triangles:
                        points.extend(triangle)
        if not points:
            return (0.0, 0.0, 0.0), 3.0

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]
        center = (
            (min(xs) + max(xs)) / 2.0,
            (min(ys) + max(ys)) / 2.0,
            (min(zs) + max(zs)) / 2.0,
        )
        radius = 0.0
        for point in points:
            dx = point[0] - center[0]
            dy = point[1] - center[1]
            dz = point[2] - center[2]
            radius = max(radius, math.sqrt(dx * dx + dy * dy + dz * dz))
        return center, max(0.9, radius + 0.45)

    def _grid_geometry(self):
        center, radius = self._fit_geometry()
        extent = max(2.4, radius * 2.0)
        step = _nice_step(extent / 8.0)
        cx = round(center[0] / step) * step
        cy = round(center[1] / step) * step
        count = max(5, min(14, int(math.ceil(radius * 1.5 / step)) + 1))
        return cx, cy, step, count

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setClipPath(clip)

        background = QLinearGradient(0, 0, 0, self.height())
        background.setColorAt(0.0, QColor("#111D33"))
        background.setColorAt(0.55, QColor("#0A1222"))
        background.setColorAt(1.0, QColor("#070B14"))
        painter.fillRect(self.rect(), background)

        glow = QRadialGradient(
            QPointF(self.width() / 2.0, self.height() * 0.18),
            max(self.width(), self.height()) * 0.75,
        )
        glow.setColorAt(0.0, QColor(99, 102, 241, 36))
        glow.setColorAt(1.0, QColor(99, 102, 241, 0))
        painter.fillRect(self.rect(), glow)

        view = _View(self._camera, self.width(), self.height())
        cx, cy, step, count = self._grid_geometry()

        if self._show_grid:
            self._draw_grid(painter, view, cx, cy, step, count)
        self._draw_world_axes(painter, view, step * 1.7)

        visible = [
            (index, pose)
            for index, pose in enumerate(self._poses)
            if pose.visible
        ] if self._show_poses else []

        if self._robot is not None:
            if self._show_skeleton:
                self._draw_joint_frames(painter, view, step)
            reduced = (
                self._interacting
                and self._visual_triangle_count > INTERACTIVE_TRIANGLE_LIMIT
            )
            if self._show_visuals and self._robot.visuals and not reduced:
                self._draw_robot_visuals(painter, view)
                if self._show_skeleton:
                    self._draw_robot_joints(painter, view)
            elif self._show_skeleton:
                self._draw_robot_body(painter, view)
            if self._show_skeleton:
                self._draw_joint_axes(painter, view, step)

        if self._show_path and len(visible) >= 2:
            self._draw_path(painter, view, visible)

        if self._show_poses:
            self._draw_frames(painter, view, visible, step)

        if self._robot is not None and self._show_skeleton:
            self._draw_robot_frames(painter, view, step)
            self._draw_robot_selection(painter, view)

        if self._vectors:
            self._draw_vectors(painter, view)
        if self._markers:
            self._draw_markers(painter, view)
        if self._measure_points:
            self._draw_measurements(painter, view)

        self._draw_hud(painter, len(visible))

        if (
            not self._poses
            and self._robot is None
            and not self._vectors
            and not self._markers
            and not self._measure_points
        ):
            self._draw_empty_state(painter)

    def _draw_grid(self, painter, view, cx, cy, step, count) -> None:
        minor = QPen(QColor(30, 41, 59, 150), 1.0)
        major = QPen(QColor(51, 65, 85, 210), 1.2)
        for i in range(-count, count + 1):
            pen = major if i % 5 == 0 else minor
            painter.setPen(pen)
            x = cx + i * step
            y = cy + i * step
            low_x = (x, cy - count * step, 0.0)
            high_x = (x, cy + count * step, 0.0)
            low_y = (cx - count * step, y, 0.0)
            high_y = (cx + count * step, y, 0.0)
            start = view.project(low_x)
            end = view.project(high_x)
            if start and end:
                painter.drawLine(start[0], end[0])
            start = view.project(low_y)
            end = view.project(high_y)
            if start and end:
                painter.drawLine(start[0], end[0])

    def _draw_world_axes(self, painter, view, length: float) -> None:
        origin = view.project((0.0, 0.0, 0.0))
        if origin is None:
            return
        for index, color in enumerate(AXIS_COLORS):
            endpoint = [0.0, 0.0, 0.0]
            endpoint[index] = length
            projected = view.project(tuple(endpoint))
            if projected is None:
                continue
            line_color = QColor(color)
            line_color.setAlpha(150)
            painter.setPen(QPen(line_color, 1.6, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(origin[0], projected[0])
            painter.setFont(mono_font(9, QFont.Bold))
            painter.setPen(QColor(color))
            screen = projected[0]
            painter.drawText(QPointF(screen.x() + 4, screen.y() - 4), AXIS_LABELS[index])

    def _draw_joint_frames(self, painter, view, step: float) -> None:
        robot = self._robot
        if robot is None or not robot.joint_frames:
            return
        length = max(0.12, step * 0.26)
        for frame in robot.joint_frames:
            origin = view.project(frame.position)
            if origin is None:
                continue
            for axis in range(3):
                direction = (
                    frame.rotation[0][axis],
                    frame.rotation[1][axis],
                    frame.rotation[2][axis],
                )
                endpoint = (
                    frame.position[0] + direction[0] * length,
                    frame.position[1] + direction[1] * length,
                    frame.position[2] + direction[2] * length,
                )
                projected = view.project(endpoint)
                if projected is None:
                    continue
                color = QColor(AXIS_COLORS[axis])
                color.setAlpha(160)
                painter.setPen(QPen(color, 1.2, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(origin[0], projected[0])

    def _draw_robot_body(self, painter, view) -> None:
        robot = self._robot
        if robot is None:
            return
        for start, end in robot.bones:
            first = view.project(start)
            second = view.project(end)
            if first is None or second is None:
                continue
            painter.setPen(
                QPen(QColor(8, 14, 26, 220), 8.0, Qt.SolidLine, Qt.RoundCap)
            )
            painter.drawLine(first[0], second[0])
        for start, end in robot.bones:
            first = view.project(start)
            second = view.project(end)
            if first is None or second is None:
                continue
            painter.setPen(
                QPen(QColor("#7DD3FC"), 3.2, Qt.SolidLine, Qt.RoundCap)
            )
            painter.drawLine(first[0], second[0])

        for index, position in enumerate(robot.joints):
            screen = view.project(position)
            if screen is None:
                continue
            radius = 4.4 if index == 0 else 3.6
            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            painter.setBrush(
                QColor("#FDE68A" if index == 0 else "#E2E8F0")
            )
            painter.drawEllipse(screen[0], radius, radius)

    def _draw_robot_visuals(self, painter, view) -> None:
        robot = self._robot
        if robot is None or not robot.visuals:
            return
        light = _normalize((0.35, -0.55, 0.75))
        width = self.width()
        height = self.height()
        faces: list[tuple[float, QPolygonF, QColor]] = []
        for visual in robot.visuals:
            base = QColor(visual.color)
            alpha = max(0, min(255, round(visual.alpha * 255)))
            selected = visual.link == self._selected_link
            for triangle in visual.triangles:
                projected = [view.project(vertex) for vertex in triangle]
                if any(item is None for item in projected):
                    continue
                points = [item[0] for item in projected]
                xs = [point.x() for point in points]
                ys = [point.y() for point in points]
                if (
                    max(xs) < -20
                    or min(xs) > width + 20
                    or max(ys) < -20
                    or min(ys) > height + 20
                ):
                    continue
                depth = sum(item[1] for item in projected) / 3.0
                first = triangle[1]
                second = triangle[2]
                origin = triangle[0]
                normal = _normalize(
                    _cross(
                        (
                            first[0] - origin[0],
                            first[1] - origin[1],
                            first[2] - origin[2],
                        ),
                        (
                            second[0] - origin[0],
                            second[1] - origin[1],
                            second[2] - origin[2],
                        ),
                    )
                )
                shade = 0.45 + 0.55 * abs(_dot(normal, light))
                if selected:
                    shade = min(1.0, shade + 0.18)
                color = QColor.fromRgbF(
                    min(1.0, base.redF() * shade),
                    min(1.0, base.greenF() * shade),
                    min(1.0, base.blueF() * shade),
                )
                color.setAlpha(alpha)
                faces.append((depth, QPolygonF(points), color))
        faces.sort(key=lambda item: item[0], reverse=True)
        painter.setPen(Qt.NoPen)
        for _, polygon, color in faces:
            painter.setBrush(color)
            painter.drawPolygon(polygon)

    def _draw_robot_joints(self, painter, view) -> None:
        robot = self._robot
        if robot is None:
            return
        selected_positions = [
            joint.position
            for joint in robot.joints_info
            if joint.name == self._selected_joint
        ]
        for index, position in enumerate(robot.joints):
            screen = view.project(position)
            if screen is None:
                continue
            selected = any(
                math.dist(position, target) < 1e-6
                for target in selected_positions
            )
            if selected:
                glow = QRadialGradient(screen[0], 16.0)
                inner = QColor("#22D3EE")
                inner.setAlpha(120)
                outer = QColor("#22D3EE")
                outer.setAlpha(0)
                glow.setColorAt(0.0, inner)
                glow.setColorAt(1.0, outer)
                painter.setPen(Qt.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(screen[0], 16.0, 16.0)
            radius = 5.6 if selected else (4.4 if index == 0 else 3.6)
            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            if selected:
                fill = "#22D3EE"
            else:
                fill = "#FDE68A" if index == 0 else "#E2E8F0"
            painter.setBrush(QColor(fill))
            painter.drawEllipse(screen[0], radius, radius)

    def _draw_joint_axes(self, painter, view, step: float) -> None:
        robot = self._robot
        if robot is None or not robot.joints_info:
            return
        length = max(0.12, step * 0.45)
        for joint in robot.joints_info:
            position = joint.position
            axis = joint.axis
            start = tuple(
                position[index] - axis[index] * length for index in range(3)
            )
            end = tuple(
                position[index] + axis[index] * length for index in range(3)
            )
            projected_start = view.project(start)
            projected_end = view.project(end)
            if projected_start is None or projected_end is None:
                continue
            selected = joint.name == self._selected_joint
            if selected:
                color = QColor("#22D3EE")
                alpha = 230
                width = 2.4
            elif joint.type in ("revolute", "continuous"):
                color = QColor("#FBBF24")
                alpha = 120
                width = 1.2
            else:
                color = QColor("#38BDF8")
                alpha = 120
                width = 1.2
            color.setAlpha(alpha)
            painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(projected_start[0], projected_end[0])
            if selected:
                screen = view.project(position)
                if screen is not None:
                    self._draw_tag(
                        painter,
                        screen[0],
                        joint.name,
                        "#22D3EE",
                        strong=True,
                        lift=18.0,
                    )

    def _draw_robot_selection(self, painter, view) -> None:
        robot = self._robot
        if robot is None or not self._selected_link:
            return
        point = self._robot_link_point(self._selected_link)
        if point is None:
            return
        projected = view.project(point)
        if projected is None:
            return
        self._draw_tag(
            painter,
            projected[0],
            self._selected_link,
            "#7DD3FC",
            strong=True,
            lift=20.0,
        )

    def _robot_link_point(self, link: str):
        robot = self._robot
        if robot is None:
            return None
        if robot.end_effector is not None and robot.end_effector.name == link:
            return robot.end_effector.position
        for index, name in enumerate(robot.bone_links):
            if name == link and index < len(robot.bones):
                return robot.bones[index][1]
        for visual in robot.visuals:
            if visual.link == link and visual.triangles:
                triangle = visual.triangles[0]
                return tuple(
                    sum(vertex[index] for vertex in triangle) / 3.0
                    for index in range(3)
                )
        return None

    def _draw_robot_frames(self, painter, view, step: float) -> None:
        robot = self._robot
        if robot is None:
            return
        length = max(0.3, step * 0.95)
        end_effector = robot.end_effector
        target = robot.target

        if end_effector is not None and target is not None:
            first = view.project(end_effector.position)
            second = view.project(target.position)
            if first is not None and second is not None:
                painter.setPen(
                    QPen(QColor(240, 171, 252, 120), 1.5, Qt.DashLine, Qt.RoundCap)
                )
                painter.drawLine(first[0], second[0])

        if target is not None:
            self._draw_frame_axes(
                painter,
                view,
                target,
                length,
                width=2.0,
                colors=("#F0ABFC", "#F0ABFC", "#F0ABFC"),
                dashed=True,
                labels=False,
            )
            screen = view.project(target.position)
            if screen is not None:
                self._draw_tag(
                    painter, screen[0], "目标", "#F0ABFC", strong=True, lift=38.0
                )

        if end_effector is not None:
            self._draw_frame_axes(
                painter,
                view,
                end_effector,
                length,
                width=2.8,
                colors=AXIS_COLORS,
                dashed=False,
                labels=True,
            )
            screen = view.project(end_effector.position)
            if screen is not None:
                self._draw_tag(
                    painter, screen[0], "末端", "#FBBF24", strong=True
                )

    def _draw_frame_axes(
        self,
        painter,
        view,
        frame: SceneFrame,
        length: float,
        width: float,
        colors: tuple[str, str, str],
        dashed: bool,
        labels: bool,
    ) -> None:
        origin = frame.position
        for axis in range(3):
            direction = (
                frame.rotation[0][axis],
                frame.rotation[1][axis],
                frame.rotation[2][axis],
            )
            endpoint = (
                origin[0] + direction[0] * length,
                origin[1] + direction[1] * length,
                origin[2] + direction[2] * length,
            )
            start = view.project(origin)
            end = view.project(endpoint)
            if start is None or end is None:
                continue
            color = QColor(colors[axis])
            if dashed:
                painter.setPen(QPen(color, width, Qt.DashLine, Qt.RoundCap))
                painter.drawLine(start[0], end[0])
            else:
                self._draw_arrow(
                    painter,
                    start[0],
                    end[0],
                    color,
                    width,
                    label=AXIS_LABELS[axis] if labels else "",
                )

    def _draw_path(self, painter, view, visible) -> None:
        for (_, first), (_, second) in zip(visible, visible[1:]):
            start = view.project(first.position)
            end = view.project(second.position)
            if start is None or end is None:
                continue
            color = QColor(second.color)
            color.setAlpha(165)
            painter.setPen(QPen(color, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(start[0], end[0])
            self._draw_chevron(painter, start[0], end[0], color)

    @staticmethod
    def _draw_chevron(painter, start: QPointF, end: QPointF, color: QColor) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 22:
            return
        ux, uy = dx / length, dy / length
        mid = QPointF((start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0)
        tip = QPointF(mid.x() + ux * 4.5, mid.y() + uy * 4.5)
        back = QPointF(mid.x() - ux * 3.0, mid.y() - uy * 3.0)
        perp = QPointF(-uy, ux)
        polygon = QPolygonF([tip, back + perp * 3.6, back - perp * 3.6])
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(polygon)

    def _draw_vectors(self, painter, view) -> None:
        for vector in self._vectors:
            if not vector.visible:
                continue
            start = view.project(vector.start)
            end = view.project(vector.end)
            if start is None or end is None:
                continue
            color = QColor(vector.color)
            glow = QColor(color)
            glow.setAlpha(60)
            painter.setPen(QPen(glow, 7.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start[0], end[0])
            self._draw_arrow(
                painter,
                start[0],
                end[0],
                color,
                3.0,
                label=vector.name if self._show_labels else "",
            )
            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            painter.setBrush(color)
            painter.drawEllipse(start[0], 4.2, 4.2)

    def _draw_markers(self, painter, view) -> None:
        for marker in self._markers:
            projected = view.project(marker.position)
            if projected is None:
                continue
            screen = projected[0]
            color = QColor(marker.color)
            painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(
                QPointF(screen.x() - 7.0, screen.y()),
                QPointF(screen.x() + 7.0, screen.y()),
            )
            painter.drawLine(
                QPointF(screen.x(), screen.y() - 7.0),
                QPointF(screen.x(), screen.y() + 7.0),
            )
            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            painter.setBrush(color)
            painter.drawEllipse(screen, 4.0, 4.0)
            if self._show_labels:
                self._draw_tag(
                    painter, screen, marker.name, marker.color, lift=12.0
                )

    def _draw_measurements(self, painter, view) -> None:
        color = QColor("#22D3EE")
        screens = []
        for point in self._measure_points:
            projected = view.project(point)
            screens.append(projected[0] if projected is not None else None)

        painter.setPen(QPen(color, 1.8, Qt.DashLine, Qt.RoundCap))
        for first, second in zip(screens, screens[1:]):
            if first is None or second is None:
                continue
            painter.drawLine(first, second)

        for index, screen in enumerate(screens):
            if screen is None:
                continue
            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            painter.setBrush(color)
            painter.drawEllipse(screen, 5.0, 5.0)
            if self._show_labels:
                self._draw_tag(
                    painter, screen, f"P{index + 1}", "#22D3EE", lift=12.0
                )

        for index, (first, second) in enumerate(zip(screens, screens[1:])):
            if first is None or second is None:
                continue
            start = self._measure_points[index]
            end = self._measure_points[index + 1]
            distance = math.sqrt(
                (end[0] - start[0]) ** 2
                + (end[1] - start[1]) ** 2
                + (end[2] - start[2]) ** 2
            )
            midpoint = QPointF(
                (first.x() + second.x()) / 2.0,
                (first.y() + second.y()) / 2.0,
            )
            self._draw_tag(
                painter, midpoint, f"{distance:.3f} m", "#22D3EE"
            )

        if len(screens) == 3 and all(screen is not None for screen in screens):
            first = self._measure_points[0]
            middle = self._measure_points[1]
            last = self._measure_points[2]
            left = (first[0] - middle[0], first[1] - middle[1], first[2] - middle[2])
            right = (last[0] - middle[0], last[1] - middle[1], last[2] - middle[2])
            left_length = math.sqrt(sum(value * value for value in left))
            right_length = math.sqrt(sum(value * value for value in right))
            if left_length > 1e-9 and right_length > 1e-9:
                cosine = sum(a * b for a, b in zip(left, right)) / (
                    left_length * right_length
                )
                angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                self._draw_tag(
                    painter,
                    screens[1],
                    f"θ {angle:.2f}°",
                    "#22D3EE",
                    strong=True,
                    lift=34.0,
                )

    def _draw_frames(self, painter, view, visible, step: float) -> None:
        axis_length = max(0.28, step * 0.62)
        items = []
        for index, pose in visible:
            projected = view.project(pose.position)
            if projected is None:
                continue
            items.append((projected[1], index, pose, projected[0]))
        items.sort(key=lambda item: item[0], reverse=True)

        for _, index, pose, origin in items:
            selected = index == self._selected
            if selected:
                halo = QRadialGradient(origin, 30.0)
                color = QColor(pose.color)
                color.setAlpha(120)
                halo.setColorAt(0.0, color)
                color_end = QColor(pose.color)
                color_end.setAlpha(0)
                halo.setColorAt(1.0, color_end)
                painter.setPen(Qt.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(origin, 30.0, 30.0)

            self._draw_axes(painter, view, pose, axis_length, selected)

            painter.setPen(QPen(QColor("#0B1220"), 2.0))
            painter.setBrush(QColor(pose.color))
            radius = 6.4 if selected else 4.8
            painter.drawEllipse(origin, radius, radius)

            if self._show_labels or selected:
                self._draw_name(painter, origin, pose, selected)

    def _draw_axes(self, painter, view, pose: ScenePose, length: float, selected: bool) -> None:
        origin = pose.position
        width = 3.0 if selected else 2.1
        for axis in range(3):
            direction = (
                pose.rotation[0][axis],
                pose.rotation[1][axis],
                pose.rotation[2][axis],
            )
            endpoint = (
                origin[0] + direction[0] * length,
                origin[1] + direction[1] * length,
                origin[2] + direction[2] * length,
            )
            start = view.project((origin[0], origin[1], origin[2]))
            end = view.project(endpoint)
            if start is None or end is None:
                continue
            color = QColor(AXIS_COLORS[axis])
            if not selected:
                color.setAlpha(228)
            self._draw_arrow(
                painter,
                start[0],
                end[0],
                color,
                width,
                label=AXIS_LABELS[axis],
            )

    @staticmethod
    def _draw_arrow(painter, start: QPointF, end: QPointF, color: QColor, width: float, label: str = "") -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1.5:
            return
        ux, uy = dx / length, dy / length
        head = 8.0
        shoulder = QPointF(end.x() - ux * head, end.y() - uy * head)
        perp = QPointF(-uy, ux)
        polygon = QPolygonF([end, shoulder + perp * 3.6, shoulder - perp * 3.6])

        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(start, QPointF(end.x() - ux * head * 0.6, end.y() - uy * head * 0.6))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(polygon)

        if label:
            painter.setFont(mono_font(9, QFont.Bold))
            painter.setPen(color)
            painter.drawText(QPointF(end.x() + ux * 7.0 + 2.0, end.y() + uy * 7.0 + 4.0), label)

    def _draw_name(self, painter, origin: QPointF, pose: ScenePose, selected: bool) -> None:
        self._draw_tag(painter, origin, pose.name, pose.color, strong=selected)

    def _draw_tag(
        self,
        painter,
        origin: QPointF,
        text: str,
        color: str,
        *,
        strong: bool = False,
        lift: float = 14.0,
    ) -> None:
        label_font = mono_font(9.5, QFont.DemiBold if strong else QFont.Normal)
        metrics = QFontMetricsF(label_font)
        width = metrics.horizontalAdvance(text) + 16.0
        height = 20.0
        left = origin.x() - width / 2.0
        left = max(8.0, min(left, self.width() - width - 8.0))
        top = max(8.0, origin.y() - height - lift)
        rect = QRectF(left, top, width, height)

        painter.setBrush(QColor(12, 20, 36, 225))
        outline = QColor(color)
        outline.setAlpha(220 if strong else 120)
        painter.setPen(QPen(outline, 1.2 if strong else 1.0))
        painter.drawRoundedRect(rect, 6.0, 6.0)

        painter.setFont(label_font)
        painter.setPen(QColor("#E2E8F0") if strong else QColor("#94A3B8"))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _draw_hud(self, painter, visible_count: int) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(9, 15, 28, 190))
        painter.drawRoundedRect(QRectF(14, 12, 150, 24), 12, 12)
        painter.setFont(mono_font(9.5))
        painter.setPen(QColor("#94A3B8"))
        painter.drawText(QRectF(14, 12, 150, 24), Qt.AlignCenter, "Z ↑  右手坐标系")

        if self._robot is not None:
            text = f"机器人 · {self._robot.name}"
            metrics = QFontMetricsF(painter.font())
            width = metrics.horizontalAdvance(text) + 24.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(9, 15, 28, 190))
            painter.drawRoundedRect(QRectF(14, 40, width, 22), 11, 11)
            painter.setPen(QColor("#7DD3FC"))
            painter.drawText(QRectF(14, 40, width, 22), Qt.AlignCenter, text)

            if self._selected_link or self._selected_joint:
                prefix = "连杆" if self._selected_link else "关节"
                selected_text = (
                    f"{prefix} · {self._selected_link or self._selected_joint}"
                )
                selected_width = (
                    metrics.horizontalAdvance(selected_text) + 24.0
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(9, 15, 28, 190))
                painter.drawRoundedRect(
                    QRectF(14, 68, selected_width, 22), 11, 11
                )
                painter.setPen(QColor("#22D3EE"))
                painter.drawText(
                    QRectF(14, 68, selected_width, 22),
                    Qt.AlignCenter,
                    selected_text,
                )

        painter.setFont(mono_font(9.5))
        painter.setPen(QColor("#64748B"))
        if self._measure_mode:
            instruction = "测量：左键点地面取点 · 两点测距 · 三点测角 · 再次点击开始新测量"
        else:
            instruction = "左键旋转 · 滚轮缩放 · 右键平移 · 双击复位"
        painter.drawText(QPointF(16, self.height() - 14), instruction)

        parts: list[str] = []
        if self._poses and self._show_poses:
            parts.append(f"显示 {visible_count} / {len(self._poses)} 帧")
        if self._vectors:
            visible_vectors = sum(1 for vector in self._vectors if vector.visible)
            parts.append(f"向量 {visible_vectors} / {len(self._vectors)}")
        if parts:
            text = " · ".join(parts)
            metrics = QFontMetricsF(painter.font())
            width = metrics.horizontalAdvance(text) + 20.0
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(
                QRectF(self.width() - width - 14, self.height() - 26, width, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                text,
            )

    def _draw_empty_state(self, painter) -> None:
        painter.setFont(mono_font(13))
        painter.setPen(QColor("#64748B"))
        painter.drawText(
            QRectF(0, 0, self.width(), self.height()),
            Qt.AlignCenter,
            "点击左侧“位姿”“向量”按钮添加数据\n或加载 URDF 机器人后在此查看三维视图",
        )
