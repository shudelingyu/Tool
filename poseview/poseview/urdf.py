"""URDF 解析、正运动学（FK）与数值 IK。

解析关节树与 URDF visual 外观（box / cylinder / sphere / STL / OBJ），
用于三维显示、FK 与内置阻尼最小二乘 IK。
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .math3d import (
    axis_angle_from_rotation,
    multiply_transform,
    rotation_from_euler,
    solve_linear,
    transform_point,
    transform_vector,
)
from .mesh import MeshError, load_triangles

_MOVABLE_TYPES = {"revolute", "continuous", "prismatic"}
_SUPPORTED_TYPES = _MOVABLE_TYPES | {"fixed"}
_VERTEX = tuple[float, float, float]
_TRIANGLE = tuple[_VERTEX, _VERTEX, _VERTEX]

_LINK_PALETTE = [
    (0.55, 0.65, 0.78, 1.0),
    (0.68, 0.73, 0.80, 1.0),
    (0.48, 0.60, 0.74, 1.0),
    (0.62, 0.70, 0.82, 1.0),
    (0.58, 0.66, 0.70, 1.0),
    (0.52, 0.58, 0.68, 1.0),
]


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
    mimic: str = ""
    mimic_multiplier: float = 1.0
    mimic_offset: float = 0.0

    @property
    def movable(self) -> bool:
        return self.type in _MOVABLE_TYPES

    @property
    def is_mimic(self) -> bool:
        return bool(self.mimic)


@dataclass
class UrdfVisual:
    link: str
    color: tuple[float, float, float, float]
    triangles: list[_TRIANGLE]


@dataclass
class JointInfo:
    name: str
    type: str
    parent: str
    child: str
    position: tuple[float, float, float]
    axis: tuple[float, float, float]
    lower: float
    upper: float
    value: float


@dataclass
class IkResult:
    success: bool
    values: dict[str, float]
    iterations: int
    position_error: float
    rotation_error: float
    message: str


@dataclass
class FkResult:
    link_frames: dict[str, list[list[float]]]
    ee_link: str
    ee_matrix: list[list[float]]
    segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]]
    segment_links: list[str]
    joint_positions: list[tuple[float, float, float]]
    joint_infos: list[JointInfo]
    joint_frames: dict[str, list[list[float]]]
    leaves: list[str]


@dataclass
class UrdfRobot:
    name: str
    link_names: list[str]
    joints: list[UrdfJoint]
    root_link: str
    leaf_links: list[str]
    warnings: list[str]
    visuals: list[UrdfVisual] = field(default_factory=list)

    @property
    def movable_joints(self) -> list[UrdfJoint]:
        return [joint for joint in self.joints if joint.movable]

    @property
    def visual_triangle_count(self) -> int:
        return sum(len(visual.triangles) for visual in self.visuals)

    def default_values(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for joint in self.movable_joints:
            if joint.is_mimic:
                continue
            value = 0.0
            if joint.lower > 0.0:
                value = joint.lower
            elif joint.upper < 0.0:
                value = joint.upper
            values[joint.name] = value
        for joint in self.movable_joints:
            if joint.is_mimic:
                values[joint.name] = self.effective_value(joint, values)
        return values

    def effective_value(
        self, joint: UrdfJoint, values: dict[str, float]
    ) -> float:
        """关节实际值：mimic 关节跟随源关节，multiplier / offset 按 URDF 约定。"""
        if not joint.is_mimic:
            return float(values.get(joint.name, 0.0))
        source = next(
            (item for item in self.joints if item.name == joint.mimic), None
        )
        if source is None:
            return float(values.get(joint.name, 0.0))
        return (
            self.effective_value(source, values) * joint.mimic_multiplier
            + joint.mimic_offset
        )

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
        segment_links: list[str] = []
        joint_infos: list[JointInfo] = []
        joint_frames: dict[str, list[list[float]]] = {}
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
                joint_frame = multiply_transform(parent_frame, joint.origin)
                joint_frames[joint.name] = joint_frame
                motion = _joint_motion(joint, self.effective_value(joint, values))
                child_frame = multiply_transform(joint_frame, motion)
                frames[joint.child] = child_frame
                depths[joint.child] = depths[parent] + 1
                visited.add(joint.child)
                segments.append((_translation(parent_frame), _translation(child_frame)))
                segment_links.append(joint.child)
                joint_positions.append(_translation(child_frame))
                if joint.movable:
                    joint_infos.append(
                        JointInfo(
                            name=joint.name,
                            type=joint.type,
                            parent=joint.parent,
                            child=joint.child,
                            position=_translation(joint_frame),
                            axis=transform_vector(joint_frame, joint.axis),
                            lower=joint.lower,
                            upper=joint.upper,
                            value=self.effective_value(joint, values),
                        )
                    )
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
            segment_links=segment_links,
            joint_positions=joint_positions,
            joint_infos=joint_infos,
            joint_frames=joint_frames,
            leaves=leaves,
        )

    def solve_ik(
        self,
        values: dict[str, float],
        ee_link: str,
        target: list[list[float]],
        locked: set[str] | None = None,
        position_weight: float = 1.0,
        orientation_weight: float = 1.0,
        max_iterations: int = 120,
        tolerance_position: float = 1e-4,
        tolerance_rotation: float = 1e-3,
    ) -> IkResult:
        """阻尼最小二乘数值 IK，返回最佳关节角与残差。"""
        locked = set(locked or ())
        position_weight = max(0.0, float(position_weight))
        orientation_weight = max(0.0, float(orientation_weight))
        if position_weight + orientation_weight < 1e-9:
            return IkResult(
                False,
                dict(values),
                0,
                math.inf,
                math.inf,
                "位置/姿态权重不能同时为 0",
            )

        current: dict[str, float] = {}
        for joint in self.movable_joints:
            value = float(values.get(joint.name, 0.0))
            current[joint.name] = max(joint.lower, min(joint.upper, value))

        initial = self.forward(current, ee_link)
        actual_ee = initial.ee_link
        by_child = {joint.child: joint for joint in self.joints}
        chain: list[UrdfJoint] = []
        link = actual_ee
        visited: set[str] = set()
        while link in by_child and link not in visited:
            visited.add(link)
            joint = by_child[link]
            chain.append(joint)
            link = joint.parent
        chain.reverse()
        movable = [
            joint
            for joint in chain
            if joint.movable and not joint.is_mimic and joint.name not in locked
        ]
        if not movable:
            position_error, rotation_error = _pose_errors(
                target, initial.ee_matrix
            )
            return IkResult(
                False,
                dict(current),
                0,
                position_error,
                rotation_error,
                "末端链上没有可动的未锁定关节",
            )

        target_position = (target[0][3], target[1][3], target[2][3])
        target_rotation = [row[:3] for row in target[:3]]
        best_values = dict(current)
        best_error = math.inf
        best_position = math.inf
        best_rotation = math.inf
        damping = 0.05
        iterations = 0

        for iteration in range(1, max_iterations + 1):
            iterations = iteration
            fk = self.forward(current, actual_ee)
            ee_matrix = fk.ee_matrix
            ee_position = _translation(ee_matrix)
            ee_rotation = [row[:3] for row in ee_matrix[:3]]
            position_vector = [
                target_position[index] - ee_position[index] for index in range(3)
            ]
            position_error = _norm(position_vector)
            rotation_matrix = _rotation_multiply(
                target_rotation, _rotation_transpose(ee_rotation)
            )
            axis, angle_degrees = axis_angle_from_rotation(rotation_matrix)
            rotation_radians = math.radians(angle_degrees)
            rotation_vector = [
                axis[index] * rotation_radians for index in range(3)
            ]
            weighted = [
                position_vector[index] * position_weight for index in range(3)
            ] + [
                rotation_vector[index] * orientation_weight
                for index in range(3)
            ]
            weighted_error = _norm(weighted)

            if weighted_error < best_error:
                best_error = weighted_error
                best_values = dict(current)
                best_position = position_error
                best_rotation = angle_degrees

            position_ok = (
                position_error <= tolerance_position or position_weight <= 0.0
            )
            rotation_ok = (
                angle_degrees <= math.degrees(tolerance_rotation)
                or orientation_weight <= 0.0
            )
            if position_ok and rotation_ok:
                return IkResult(
                    True,
                    dict(current),
                    iteration,
                    position_error,
                    angle_degrees,
                    "收敛",
                )

            columns: list[list[float]] = []
            for joint in movable:
                joint_frame = multiply_transform(
                    fk.link_frames[joint.parent], joint.origin
                )
                joint_position = _translation(joint_frame)
                axis_world = transform_vector(joint_frame, joint.axis)
                if joint.type == "prismatic":
                    linear = list(axis_world)
                    angular = [0.0, 0.0, 0.0]
                else:
                    offset = [
                        ee_position[index] - joint_position[index]
                        for index in range(3)
                    ]
                    linear = _cross(list(axis_world), offset)
                    angular = list(axis_world)
                columns.append(
                    [linear[index] * position_weight for index in range(3)]
                    + [angular[index] * orientation_weight for index in range(3)]
                )

            jacobian = [
                [columns[column][row] for column in range(len(columns))]
                for row in range(6)
            ]
            normal = [
                [
                    sum(
                        jacobian[row][column] * jacobian[other][column]
                        for column in range(len(columns))
                    )
                    + (damping * damping if row == other else 0.0)
                    for other in range(6)
                ]
                for row in range(6)
            ]
            step = solve_linear(normal, weighted)
            if step is None:
                damping = min(1.0, damping * 2.0)
                continue

            delta = [
                sum(jacobian[row][column] * step[row] for row in range(6))
                for column in range(len(columns))
            ]
            maximum = max((abs(value) for value in delta), default=0.0)
            scale = 1.0 if maximum <= 0.25 else 0.25 / maximum
            candidate = dict(current)
            for joint, change in zip(movable, delta):
                value = current[joint.name] + change * scale
                candidate[joint.name] = max(
                    joint.lower, min(joint.upper, value)
                )

            candidate_fk = self.forward(candidate, actual_ee)
            candidate_position, candidate_rotation = _pose_errors(
                target, candidate_fk.ee_matrix
            )
            candidate_vector = _weighted_error(
                target,
                candidate_fk.ee_matrix,
                position_weight,
                orientation_weight,
            )
            candidate_error = _norm(candidate_vector)
            if candidate_error < weighted_error:
                current = candidate
                damping = max(0.005, damping * 0.5)
            else:
                damping = min(1.0, damping * 2.0)

        success = (
            (best_position <= tolerance_position or position_weight <= 0.0)
            and (
                best_rotation <= math.degrees(tolerance_rotation)
                or orientation_weight <= 0.0
            )
        )
        return IkResult(
            success,
            best_values,
            iterations,
            best_position,
            best_rotation,
            "收敛" if success else "达到最大迭代次数，未完全收敛",
        )


def load_urdf(path: str) -> UrdfRobot:
    try:
        tree = ET.parse(path)
    except OSError as exc:
        raise UrdfError(f"无法读取文件：{exc}") from exc
    except ET.ParseError as exc:
        raise UrdfError(f"XML 解析失败：{exc}") from exc
    return parse_urdf(tree.getroot(), Path(path).resolve().parent)


def parse_urdf_text(
    text: str, base_dir: Path | str | None = None
) -> UrdfRobot:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UrdfError(f"XML 解析失败：{exc}") from exc
    directory = Path(base_dir) if base_dir is not None else None
    return parse_urdf(root, directory)


def parse_urdf(
    root: ET.Element, base_dir: Path | None = None
) -> UrdfRobot:
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

    named_materials: dict[str, tuple[float, float, float, float]] = {}
    for material in root.findall("material"):
        material_name = material.get("name")
        color = _color_from_element(material)
        if material_name and color is not None:
            named_materials[material_name] = color

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
        mimic_name = ""
        mimic_multiplier = 1.0
        mimic_offset = 0.0
        mimic_element = element.find("mimic")
        if mimic_element is not None:
            mimic_name = (mimic_element.get("joint") or "").strip()
            try:
                mimic_multiplier = float(
                    mimic_element.get("multiplier") or 1.0
                )
                mimic_offset = float(mimic_element.get("offset") or 0.0)
            except ValueError:
                mimic_multiplier = 1.0
                mimic_offset = 0.0
                warnings.append(
                    f"关节 {joint_name} 的 mimic multiplier / offset 无效，按 1 / 0 处理"
                )
            if not mimic_name:
                warnings.append(f"关节 {joint_name} 的 mimic 缺少 joint，按独立关节处理")

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
                mimic=mimic_name,
                mimic_multiplier=mimic_multiplier,
                mimic_offset=mimic_offset,
            )
        )

    _validate_mimic(joints, warnings)

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

    visuals: list[UrdfVisual] = []
    for link_index, element in enumerate(root.findall("link")):
        link_name = element.get("name", "")
        for visual_index, visual_element in enumerate(element.findall("visual")):
            visual = _parse_visual(
                link_name,
                visual_element,
                named_materials,
                base_dir,
                warnings,
                link_index,
                visual_index,
            )
            if visual is not None:
                visuals.append(visual)

    return UrdfRobot(
        name=name,
        link_names=link_names,
        joints=joints,
        root_link=root_link,
        leaf_links=leaf_links,
        warnings=warnings,
        visuals=visuals,
    )


def _parse_visual(
    link: str,
    element: ET.Element,
    named_materials: dict[str, tuple[float, float, float, float]],
    base_dir: Path | None,
    warnings: list[str],
    link_index: int,
    visual_index: int,
) -> UrdfVisual | None:
    geometry = element.find("geometry")
    if geometry is None:
        return None

    origin = _identity()
    origin_element = element.find("origin")
    if origin_element is not None:
        xyz = _vector(origin_element.get("xyz"), (0.0, 0.0, 0.0), link)
        rpy = _vector(origin_element.get("rpy"), (0.0, 0.0, 0.0), link)
        origin = _origin_matrix(xyz, rpy)

    color = None
    material = element.find("material")
    if material is not None:
        color = _color_from_element(material)
        if color is None:
            color = named_materials.get(material.get("name") or "")
    if color is None:
        color = _LINK_PALETTE[(link_index + visual_index) % len(_LINK_PALETTE)]

    triangles: list[_TRIANGLE] | None = None
    box = geometry.find("box")
    cylinder = geometry.find("cylinder")
    sphere = geometry.find("sphere")
    mesh = geometry.find("mesh")
    if box is not None:
        size = _vector(box.get("size"), (0.1, 0.1, 0.1), link)
        triangles = _box_triangles(size)
    elif cylinder is not None:
        radius = _number(cylinder.get("radius"), 0.05, link)
        length = _number(cylinder.get("length"), 0.1, link)
        triangles = _cylinder_triangles(radius, length)
    elif sphere is not None:
        radius = _number(sphere.get("radius"), 0.05, link)
        triangles = _sphere_triangles(radius)
    elif mesh is not None:
        filename = mesh.get("filename")
        if not filename:
            warnings.append(f"link {link} 的 mesh 缺少 filename")
            return None
        path = _resolve_mesh_path(filename, base_dir)
        if path is None:
            warnings.append(f"找不到 mesh 文件：{filename}（link {link}）")
            return None
        if path.suffix.lower() == ".dae":
            warnings.append(f"暂不支持 COLLADA 外观：{filename}（link {link}）")
            return None
        scale = _vector(mesh.get("scale"), (1.0, 1.0, 1.0), link)
        try:
            raw = load_triangles(path)
        except MeshError as exc:
            warnings.append(f"link {link} 的 mesh 无法加载：{exc}")
            return None
        triangles = [
            tuple(
                (
                    vertex[0] * scale[0],
                    vertex[1] * scale[1],
                    vertex[2] * scale[2],
                )
                for vertex in triangle
            )
            for triangle in raw
        ]
    else:
        return None

    if not triangles:
        return None
    transformed = [
        tuple(transform_point(origin, vertex) for vertex in triangle)
        for triangle in triangles
    ]
    return UrdfVisual(link=link, color=color, triangles=transformed)


def _color_from_element(
    element: ET.Element,
) -> tuple[float, float, float, float] | None:
    color_element = element.find("color")
    if color_element is None:
        return None
    raw = color_element.get("rgba") or color_element.get("rgb")
    if not raw:
        return None
    parts = raw.replace(",", " ").split()
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    if len(values) < 3:
        return None
    alpha = values[3] if len(values) >= 4 else 1.0
    return (
        max(0.0, min(1.0, values[0])),
        max(0.0, min(1.0, values[1])),
        max(0.0, min(1.0, values[2])),
        max(0.0, min(1.0, alpha)),
    )


def _resolve_mesh_path(filename: str, base_dir: Path | None) -> Path | None:
    if base_dir is None:
        return None
    raw = filename.strip()
    candidates: list[Path] = []
    if raw.startswith("package://"):
        rest = raw[len("package://") :]
        package, _, relative = rest.partition("/")
        for parent in [base_dir, *base_dir.parents]:
            if relative:
                candidates.append(parent / relative)
            if package and relative:
                candidates.append(parent / package / relative)
    elif raw.startswith("file://"):
        candidates.append(Path(raw[len("file://") :]))
    else:
        candidates.append(base_dir / raw)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _box_triangles(size: tuple[float, float, float]) -> list[_TRIANGLE]:
    half_x, half_y, half_z = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    p000 = (-half_x, -half_y, -half_z)
    p100 = (half_x, -half_y, -half_z)
    p110 = (half_x, half_y, -half_z)
    p010 = (-half_x, half_y, -half_z)
    p001 = (-half_x, -half_y, half_z)
    p101 = (half_x, -half_y, half_z)
    p111 = (half_x, half_y, half_z)
    p011 = (-half_x, half_y, half_z)
    return [
        (p000, p010, p110),
        (p000, p110, p100),
        (p001, p101, p111),
        (p001, p111, p011),
        (p000, p100, p101),
        (p000, p101, p001),
        (p010, p011, p111),
        (p010, p111, p110),
        (p000, p001, p011),
        (p000, p011, p010),
        (p100, p110, p111),
        (p100, p111, p101),
    ]


def _cylinder_triangles(
    radius: float, length: float, segments: int = 20
) -> list[_TRIANGLE]:
    radius = abs(radius)
    half = abs(length) / 2.0
    segments = max(3, segments)
    triangles: list[_TRIANGLE] = []
    bottom_center = (0.0, 0.0, -half)
    top_center = (0.0, 0.0, half)
    for index in range(segments):
        angle0 = 2.0 * math.pi * index / segments
        angle1 = 2.0 * math.pi * (index + 1) / segments
        b0 = (radius * math.cos(angle0), radius * math.sin(angle0), -half)
        b1 = (radius * math.cos(angle1), radius * math.sin(angle1), -half)
        t0 = (radius * math.cos(angle0), radius * math.sin(angle0), half)
        t1 = (radius * math.cos(angle1), radius * math.sin(angle1), half)
        triangles.append((b0, b1, t1))
        triangles.append((b0, t1, t0))
        triangles.append((bottom_center, b1, b0))
        triangles.append((top_center, t0, t1))
    return triangles


def _sphere_triangles(
    radius: float, rings: int = 12, segments: int = 20
) -> list[_TRIANGLE]:
    radius = abs(radius)
    rings = max(3, rings)
    segments = max(3, segments)
    triangles: list[_TRIANGLE] = []
    for ring in range(rings):
        phi0 = -math.pi / 2.0 + math.pi * ring / rings
        phi1 = -math.pi / 2.0 + math.pi * (ring + 1) / rings
        z0 = radius * math.sin(phi0)
        z1 = radius * math.sin(phi1)
        r0 = radius * math.cos(phi0)
        r1 = radius * math.cos(phi1)
        for segment in range(segments):
            angle0 = 2.0 * math.pi * segment / segments
            angle1 = 2.0 * math.pi * (segment + 1) / segments
            p00 = (r0 * math.cos(angle0), r0 * math.sin(angle0), z0)
            p01 = (r0 * math.cos(angle1), r0 * math.sin(angle1), z0)
            p10 = (r1 * math.cos(angle0), r1 * math.sin(angle0), z1)
            p11 = (r1 * math.cos(angle1), r1 * math.sin(angle1), z1)
            triangles.append((p00, p10, p11))
            triangles.append((p00, p11, p01))
    return triangles


def _pose_errors(
    target: list[list[float]], ee_matrix: list[list[float]]
) -> tuple[float, float]:
    target_position = (target[0][3], target[1][3], target[2][3])
    ee_position = _translation(ee_matrix)
    position_error = math.sqrt(
        sum(
            (target_position[index] - ee_position[index]) ** 2
            for index in range(3)
        )
    )
    target_rotation = [row[:3] for row in target[:3]]
    ee_rotation = [row[:3] for row in ee_matrix[:3]]
    axis, angle = axis_angle_from_rotation(
        _rotation_multiply(target_rotation, _rotation_transpose(ee_rotation))
    )
    del axis
    return position_error, angle


def _weighted_error(
    target: list[list[float]],
    ee_matrix: list[list[float]],
    position_weight: float,
    orientation_weight: float,
) -> list[float]:
    target_position = (target[0][3], target[1][3], target[2][3])
    ee_position = _translation(ee_matrix)
    position = [
        (target_position[index] - ee_position[index]) * position_weight
        for index in range(3)
    ]
    target_rotation = [row[:3] for row in target[:3]]
    ee_rotation = [row[:3] for row in ee_matrix[:3]]
    axis, angle = axis_angle_from_rotation(
        _rotation_multiply(target_rotation, _rotation_transpose(ee_rotation))
    )
    radians = math.radians(angle) * orientation_weight
    return position + [axis[index] * radians for index in range(3)]


def _rotation_multiply(
    first: list[list[float]], second: list[list[float]]
) -> list[list[float]]:
    return [
        [
            sum(first[row][index] * second[index][column] for index in range(3))
            for column in range(3)
        ]
        for row in range(3)
    ]


def _rotation_transpose(rotation: list[list[float]]) -> list[list[float]]:
    return [
        [rotation[column][row] for column in range(3)] for row in range(3)
    ]


def _cross(first: list[float], second: list[float]) -> list[float]:
    return [
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    ]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _validate_mimic(joints: list[UrdfJoint], warnings: list[str]) -> None:
    """校验 mimic 目标存在且不循环，无效时退回独立关节。"""
    by_name = {joint.name: joint for joint in joints}
    for joint in joints:
        if not joint.mimic:
            continue
        if joint.mimic not in by_name:
            warnings.append(
                f"关节 {joint.name} 的 mimic 目标 {joint.mimic} 不存在，按独立关节处理"
            )
            joint.mimic = ""
            continue
        seen = {joint.name}
        cursor = by_name[joint.mimic]
        while cursor.mimic:
            if cursor.name in seen:
                warnings.append(f"关节 {joint.name} 的 mimic 形成循环，按独立关节处理")
                joint.mimic = ""
                break
            seen.add(cursor.name)
            cursor = by_name.get(cursor.mimic)
            if cursor is None:
                break


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
