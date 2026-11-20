"""深色三维场景：地面网格、世界坐标轴、位姿坐标轴与轨迹。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
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

AXIS_COLORS = ("#F87171", "#4ADE80", "#60A5FA")
AXIS_LABELS = ("X", "Y", "Z")


@dataclass
class ScenePose:
    name: str
    color: str
    position: tuple[float, float, float]
    rotation: list[list[float]]
    visible: bool = True


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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self._camera = _Camera()
        self._poses: list[ScenePose] = []
        self._robot: RobotSkeleton | None = None
        self._selected = -1
        self._show_grid = True
        self._show_path = True
        self._show_labels = True
        self._show_poses = True
        self._press_pos = None
        self._last_pos = None
        self._drag_button = None
        self._moved = False

    # ------------------------------------------------------------------
    # 数据与选项
    # ------------------------------------------------------------------

    def set_poses(self, poses: list[ScenePose]) -> None:
        self._poses = poses
        if self._selected >= len(poses):
            self._selected = -1
        self.update()

    def set_selected(self, index: int) -> None:
        self._selected = index
        self.update()

    def set_robot(self, robot: RobotSkeleton | None) -> None:
        self._robot = robot
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
            self.setCursor(Qt.ClosedHandCursor)
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
            self.update()
        elif event.buttons() & (Qt.RightButton | Qt.MiddleButton):
            self._pan(delta.x(), delta.y())
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.OpenHandCursor)
        if (
            event.button() == Qt.LeftButton
            and not self._moved
            and self._press_pos is not None
        ):
            self._pick(event.pos())
        self._last_pos = None
        self._drag_button = None
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.reset_view()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._camera.distance = max(0.08, min(1e6, self._camera.distance * math.exp(-steps * 0.13)))
            self.update()
        event.accept()

    def _pan(self, dx: int, dy: int) -> None:
        view = _View(self._camera, self.width(), self.height())
        scale = self._camera.distance / view.focal
        for i in range(3):
            self._camera.target[i] += (-view.right[i] * dx + view.up[i] * dy) * scale

    def _pick(self, pos) -> None:
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

    # ------------------------------------------------------------------
    # 场景几何
    # ------------------------------------------------------------------

    def _fit_geometry(self):
        points: list[tuple[float, float, float]] = []
        if self._show_poses:
            poses = [pose for pose in self._poses if pose.visible] or self._poses
            points.extend(pose.position for pose in poses)
        if self._robot is not None:
            for start, end in self._robot.bones:
                points.append(start)
                points.append(end)
            points.extend(self._robot.joints)
            if self._robot.end_effector is not None:
                points.append(self._robot.end_effector.position)
            if self._robot.target is not None:
                points.append(self._robot.target.position)
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
            self._draw_joint_frames(painter, view, step)
            self._draw_robot_body(painter, view)

        if self._show_path and len(visible) >= 2:
            self._draw_path(painter, view, visible)

        if self._show_poses:
            self._draw_frames(painter, view, visible, step)

        if self._robot is not None:
            self._draw_robot_frames(painter, view, step)

        self._draw_hud(painter, len(visible))

        if not self._poses and self._robot is None:
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

        painter.setFont(mono_font(9.5))
        painter.setPen(QColor("#64748B"))
        painter.drawText(
            QPointF(16, self.height() - 14),
            "左键旋转 · 滚轮缩放 · 右键平移 · 双击复位",
        )

        if self._poses and self._show_poses:
            text = f"显示 {visible_count} / {len(self._poses)} 帧"
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
            "粘贴位姿矩阵并添加\n即可在此查看三维位姿",
        )
