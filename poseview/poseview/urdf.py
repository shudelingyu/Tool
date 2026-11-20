"""URDF 解析与正运动学（FK）。

只解析关节树、关节轴与限位，用于骨架显示和 FK / IK 校验；
不加载 mesh / visual 外观。
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .math3d import multiply_transform, rotation_from_euler

_MOVABLE_TYPES = {"revolute", "continuous", "prismatic"}
_SUPPORTED_TYPES = _MOVABLE_TYPES | {"fixed"}


class UrdfError(ValueError):
    """URDF 文件无法解析。"""


@dataclass
class UrdfJoint:
    name: str
    type: str
    parent: str
    child: str
    origin: list[list[float]]
    axis: tuple[float, float, float]
    lower: float
    upper: float

    @property
    def movable(self) -> bool:
        return self.type in _MOVABLE_TYPES


@dataclass
class FkResult:
    link_frames: dict[str, list[list[float]]]
    ee_link: str
    ee_matrix: list[list[float]]
    segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]]
    joint_positions: list[tuple[float, float, float]]
    leaves: list[str]


@dataclass
class UrdfRobot:
    name: str
    link_names: list[str]
    joints: list[UrdfJoint]
    root_link: str
    leaf_links: list[str]
    warnings: list[str]

    @property
    def movable_joints(self) -> list[UrdfJoint]:
        return [joint for joint in self.joints if joint.movable]

    def default_values(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for joint in self.movable_joints:
            value = 0.0
            if joint.lower > 0.0:
                value = joint.lower
            elif joint.upper < 0.0:
                value = joint.upper
            values[joint.name] = value
        return values

    def default_ee_link(self) -> str:
        if self.leaf_links:
            return self.leaf_links[0]
        if self.link_names:
            return self.link_names[-1]
        return ""

    def forward(
        self,
        values: dict[str, float],
        ee_link: str | None = None,
    ) -> FkResult:
        children: dict[str, list[UrdfJoint]] = {}
        for joint in self.joints:
            children.setdefault(joint.parent, []).append(joint)

        frames: dict[str, list[list[float]]] = {self.root_link: _identity()}
        depths: dict[str, int] = {self.root_link: 0}
        segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        joint_positions: list[tuple[float, float, float]] = [
            _translation(frames[self.root_link])
        ]

        stack = [self.root_link]
        visited = {self.root_link}
        while stack:
            parent = stack.pop()
            parent_frame = frames[parent]
            for joint in children.get(parent, []):
                if joint.child in visited:
                    continue
                motion = _joint_motion(joint, values.get(joint.name, 0.0))
                child_frame = multiply_transform(
                    multiply_transform(parent_frame, joint.origin), motion
                )
                frames[joint.child] = child_frame
                depths[joint.child] = depths[parent] + 1
                visited.add(joint.child)
                segments.append((_translation(parent_frame), _translation(child_frame)))
                joint_positions.append(_translation(child_frame))
                stack.append(joint.child)

        leaves = [link for link in self.leaf_links if link in frames]
        if not ee_link or ee_link not in frames:
            if leaves:
                ee_link = max(leaves, key=lambda link: depths.get(link, 0))
            else:
                ee_link = self.root_link
        ee_matrix = frames.get(ee_link, frames[self.root_link])
        return FkResult(
            link_frames=frames,
            ee_link=ee_link,
            ee_matrix=ee_matrix,
            segments=segments,
            joint_positions=joint_positions,
            leaves=leaves,
        )


def load_urdf(path: str) -> UrdfRobot:
    try:
        tree = ET.parse(path)
    except OSError as exc:
        raise UrdfError(f"无法读取文件：{exc}") from exc
    except ET.ParseError as exc:
        raise UrdfError(f"XML 解析失败：{exc}") from exc
    return parse_urdf(tree.getroot())


def parse_urdf_text(text: str) -> UrdfRobot:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UrdfError(f"XML 解析失败：{exc}") from exc
    return parse_urdf(root)


def parse_urdf(root: ET.Element) -> UrdfRobot:
    if root.tag != "robot":
        raise UrdfError("根节点必须是 <robot>")

    name = root.get("name") or "robot"
    link_names: list[str] = []
    for element in root.findall("link"):
        link_name = element.get("name")
        if not link_name:
            raise UrdfError("<link> 缺少 name 属性")
        if link_name in link_names:
            raise UrdfError(f"link 名称重复：{link_name}")
        link_names.append(link_name)
    if not link_names:
        raise UrdfError("URDF 中没有 <link>")

    joints: list[UrdfJoint] = []
    child_links: set[str] = set()
    joint_names: set[str] = set()
    warnings: list[str] = []

    for element in root.findall("joint"):
        joint_name = element.get("name")
        if not joint_name:
            raise UrdfError("<joint> 缺少 name 属性")
        if joint_name in joint_names:
            raise UrdfError(f"joint 名称重复：{joint_name}")
        joint_names.add(joint_name)

        joint_type = element.get("type", "fixed")
        parent_element = element.find("parent")
        child_element = element.find("child")
        if parent_element is None or child_element is None:
            raise UrdfError(f"关节 {joint_name} 缺少 parent / child")
        parent = parent_element.get("link", "")
        child = child_element.get("link", "")
        if parent not in link_names or child not in link_names:
            raise UrdfError(f"关节 {joint_name} 引用了不存在的 link")
        if child in child_links:
            raise UrdfError(f"link {child} 有多个父关节")
        child_links.add(child)

        origin_element = element.find("origin")
        xyz = _vector(origin_element.get("xyz") if origin_element is not None else None, (0.0, 0.0, 0.0), joint_name)
        rpy = _vector(origin_element.get("rpy") if origin_element is not None else None, (0.0, 0.0, 0.0), joint_name)
        origin = _origin_matrix(xyz, rpy)

        axis_element = element.find("axis")
        axis = _vector(axis_element.get("xyz") if axis_element is not None else None, (1.0, 0.0, 0.0), joint_name)
        length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
        if length < 1e-9:
            warnings.append(f"关节 {joint_name} 的 axis 为 0，按 X 轴处理")
            axis = (1.0, 0.0, 0.0)
        else:
            axis = (axis[0] / length, axis[1] / length, axis[2] / length)

        lower, upper = _limits(element, joint_type, joint_name, warnings)
        if joint_type not in _SUPPORTED_TYPES:
            warnings.append(f"关节 {joint_name} 类型 {joint_type} 暂不支持，按固定关节处理")
            lower, upper = 0.0, 0.0
        if element.find("mimic") is not None:
            warnings.append(f"关节 {joint_name} 使用 mimic，暂按独立关节处理")

        joints.append(
            UrdfJoint(
                name=joint_name,
                type=joint_type,
                parent=parent,
                child=child,
                origin=origin,
                axis=axis,
                lower=lower,
                upper=upper,
            )
        )

    if not joints:
        raise UrdfError("URDF 中没有 <joint>")

    roots = [link for link in link_names if link not in child_links]
    if not roots:
        raise UrdfError("URDF 关节形成闭环，找不到根 link")
    if len(roots) > 1:
        warnings.append(f"检测到 {len(roots)} 个根 link，使用 {roots[0]}")
    root_link = roots[0]

    children: dict[str, list[UrdfJoint]] = {}
    for joint in joints:
        children.setdefault(joint.parent, []).append(joint)

    depths = {root_link: 0}
    reachable = {root_link}
    stack = [root_link]
    while stack:
        parent = stack.pop()
        for joint in children.get(parent, []):
            if joint.child in reachable:
                continue
            reachable.add(joint.child)
            depths[joint.child] = depths[parent] + 1
            stack.append(joint.child)

    missing = [link for link in link_names if link not in reachable]
    if missing:
        warnings.append(f"{len(missing)} 个 link 未连接到根节点，已忽略")

    order = {link: index for index, link in enumerate(link_names)}
    leaf_links = [link for link in reachable if not children.get(link)]
    leaf_links.sort(key=lambda link: (-depths.get(link, 0), order.get(link, 0)))
    if not leaf_links:
        raise UrdfError("URDF 中没有末端 link")

    return UrdfRobot(
        name=name,
        link_names=link_names,
        joints=joints,
        root_link=root_link,
        leaf_links=leaf_links,
        warnings=warnings,
    )


def _limits(
    joint_element: ET.Element,
    joint_type: str,
    joint_name: str,
    warnings: list[str],
) -> tuple[float, float]:
    if joint_type == "continuous":
        return -math.pi, math.pi
    if joint_type == "revolute":
        default = (-math.pi, math.pi)
    elif joint_type == "prismatic":
        default = (-0.5, 0.5)
    else:
        return 0.0, 0.0

    limit_element = joint_element.find("limit")
    lower = default[0]
    upper = default[1]
    if limit_element is not None:
        lower = _number(limit_element.get("lower"), lower, joint_name)
        upper = _number(limit_element.get("upper"), upper, joint_name)
    else:
        warnings.append(f"关节 {joint_name} 缺少 limit，使用默认范围")
    if lower > upper:
        warnings.append(f"关节 {joint_name} 的 limit 上下界颠倒，已交换")
        lower, upper = upper, lower
    if abs(upper - lower) < 1e-9:
        upper = lower + 1e-6
    return lower, upper


def _number(value: str | None, default: float, joint_name: str) -> float:
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise UrdfError(f"关节 {joint_name} 的 limit 数值无效：{value}") from exc


def _vector(
    value: str | None,
    default: tuple[float, float, float],
    joint_name: str,
) -> tuple[float, float, float]:
    if value is None or not value.strip():
        return default
    parts = value.replace(",", " ").split()
    if len(parts) != 3:
        raise UrdfError(f"关节 {joint_name} 的向量需要 3 个数：{value}")
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as exc:
        raise UrdfError(f"关节 {joint_name} 的向量数值无效：{value}") from exc


def _origin_matrix(
    xyz: tuple[float, float, float], rpy: tuple[float, float, float]
) -> list[list[float]]:
    # URDF 的 rpy 单位为弧度，rotation_from_euler 接收角度
    rotation = rotation_from_euler(
        math.degrees(rpy[0]), math.degrees(rpy[1]), math.degrees(rpy[2])
    )
    return [
        [rotation[0][0], rotation[0][1], rotation[0][2], xyz[0]],
        [rotation[1][0], rotation[1][1], rotation[1][2], xyz[1]],
        [rotation[2][0], rotation[2][1], rotation[2][2], xyz[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _joint_motion(joint: UrdfJoint, value: float) -> list[list[float]]:
    if joint.type in ("revolute", "continuous"):
        rotation = _axis_angle_rotation(joint.axis, value)
        return [
            [rotation[0][0], rotation[0][1], rotation[0][2], 0.0],
            [rotation[1][0], rotation[1][1], rotation[1][2], 0.0],
            [rotation[2][0], rotation[2][1], rotation[2][2], 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    if joint.type == "prismatic":
        return [
            [1.0, 0.0, 0.0, joint.axis[0] * value],
            [0.0, 1.0, 0.0, joint.axis[1] * value],
            [0.0, 0.0, 1.0, joint.axis[2] * value],
            [0.0, 0.0, 0.0, 1.0],
        ]
    return _identity()


def _axis_angle_rotation(
    axis: tuple[float, float, float], angle: float
) -> list[list[float]]:
    x, y, z = axis
    cosine = math.cos(angle)
    sine = math.sin(angle)
    one = 1.0 - cosine
    return [
        [cosine + x * x * one, x * y * one - z * sine, x * z * one + y * sine],
        [y * x * one + z * sine, cosine + y * y * one, y * z * one - x * sine],
        [z * x * one - y * sine, z * y * one + x * sine, cosine + z * z * one],
    ]


def _translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    return (matrix[0][3], matrix[1][3], matrix[2][3])


def _identity() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
