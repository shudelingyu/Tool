"""关节角轨迹文件解析、列映射与单位换算。

支持 .cst / .cvt / .csv / .txt 等文本格式：
- 首行可为 ``name J1 J2 ...`` 表头，也可没有表头；
- 数据行可为纯数值，或 ``actpos: v1 v2 ...`` 形式；
- 自动跳过空行、注释行与说明行；
- 列名可按关节名称 / J1 编号自动匹配，也可按可动关节顺序映射。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .urdf import UrdfJoint, UrdfRobot

_SPLIT = re.compile(r"[\s,;|]+")
_NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?$")
_JOINT_ALIAS = re.compile(r"^(?:j(?:oint)?|q)(\d+)$")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-:]*$")
_HEADER_LABELS = {"name", "joint", "joints"}


class TrajectoryError(ValueError):
    """轨迹文件无法解析。"""


@dataclass
class JointTrajectory:
    path: str
    columns: list[str]
    frames: list[list[float]]
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def column_count(self) -> int:
        return len(self.frames[0]) if self.frames else 0


def trajectory_joints(robot: UrdfRobot) -> list[UrdfJoint]:
    """参与轨迹映射的关节：可动且非 mimic。"""
    return [
        joint for joint in robot.movable_joints if not joint.is_mimic
    ]


def load_trajectory(path: str | Path) -> JointTrajectory:
    """读取轨迹文件，返回各帧原始数值与列名。"""
    file_path = Path(path)
    try:
        text = _read_text_auto(file_path)
    except OSError as exc:
        raise TrajectoryError(f"无法读取文件：{exc}") from exc

    columns: list[str] = []
    frames: list[list[float]] = []
    labels: list[str] = []
    warnings: list[str] = []
    width: int | None = None

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith(("#", "//")):
            continue
        tokens = [token for token in _SPLIT.split(line) if token]
        if not tokens:
            continue

        values = _to_floats(tokens)
        label = ""
        if values is None:
            rest = _to_floats(tokens[1:])
            if rest is not None:
                label = tokens[0].rstrip(":")
                values = rest
            else:
                if not columns and _looks_like_header(tokens):
                    head = (
                        tokens[1:]
                        if tokens[0].lower() in _HEADER_LABELS
                        else tokens
                    )
                    columns = [token.rstrip(":") for token in head]
                continue

        if not values:
            continue
        if width is None:
            width = len(values)
        elif len(values) != width:
            warnings.append(
                f"第 {line_number} 行有 {len(values)} 个关节角，"
                f"与首行 {width} 个不一致，已跳过"
            )
            continue
        frames.append(values)
        labels.append(label)

    if not frames:
        raise TrajectoryError(
            "未解析到关节角数据，请确认文件包含「名称（可选）+ 关节角」数据行"
        )

    if columns and len(columns) != width:
        warnings.append(
            f"表头有 {len(columns)} 列，数据行有 {width} 列，已按数据行对齐"
        )
        if len(columns) < width:
            columns += [""] * (width - len(columns))
        else:
            columns = columns[:width]

    return JointTrajectory(
        path=str(file_path),
        columns=columns,
        frames=frames,
        labels=labels,
        warnings=warnings,
    )


def resolve_mapping(
    columns: list[str],
    joints: list[UrdfJoint],
    mode: str = "auto",
    column_count: int | None = None,
) -> tuple[list[int | None], list[str]]:
    """把轨迹列映射到关节索引，返回 (映射, 提示)。

    auto：先按关节名称匹配，再识别 J1 / joint1 / q1 编号；
    order：按可动关节顺序映射；
    column_count：无表头时可指定轨迹列数。
    """
    if column_count is not None:
        count = max(0, int(column_count))
    elif columns:
        count = len(columns)
    else:
        count = len(joints)
    mapping: list[int | None] = []
    warnings: list[str] = []
    if mode == "order" or not columns or not any(columns):
        for index in range(count):
            mapping.append(index if index < len(joints) else None)
        if columns and count > len(joints):
            warnings.append(
                f"轨迹有 {count} 列，关节只有 {len(joints)} 个，多余列已忽略"
            )
        return mapping, warnings

    by_name = {_normalize(joint.name): index for index, joint in enumerate(joints)}
    used: set[int] = set()
    for position in range(count):
        column = columns[position] if position < len(columns) else ""
        normalized = _normalize(column)
        index: int | None = None
        if normalized in by_name:
            index = by_name[normalized]
        else:
            match = _JOINT_ALIAS.match(normalized)
            if match is not None:
                candidate = int(match.group(1)) - 1
                if 0 <= candidate < len(joints):
                    index = candidate
        if index is None:
            mapping.append(None)
            if column:
                warnings.append(f"列 {column} 未匹配到关节")
        elif index in used:
            mapping.append(None)
            warnings.append(f"列 {column} 与前面的列映射到同一关节，已忽略")
        else:
            mapping.append(index)
            used.add(index)
    return mapping, warnings


def frame_values(
    robot: UrdfRobot,
    frame: list[float],
    mapping: list[int | None],
    base_values: dict[str, float],
    degrees: bool = False,
) -> dict[str, float]:
    """把一帧原始数值转为 URDF 关节值字典（弧度 / 米）。"""
    joints = trajectory_joints(robot)
    values = dict(base_values)
    for column, index in enumerate(mapping):
        if index is None or index >= len(joints) or column >= len(frame):
            continue
        joint = joints[index]
        value = float(frame[column])
        if degrees and joint.type in ("revolute", "continuous"):
            value = math.radians(value)
        values[joint.name] = value
    for joint in robot.movable_joints:
        if joint.is_mimic:
            values[joint.name] = robot.effective_value(joint, values)
    return values


def _read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _to_floats(tokens: list[str]) -> list[float] | None:
    values: list[float] = []
    for token in tokens:
        cleaned = token.strip()
        if not _NUMBER.match(cleaned):
            return None
        value = float(cleaned)
        if not math.isfinite(value):
            return None
        values.append(value)
    return values


def _looks_like_header(tokens: list[str]) -> bool:
    if len(tokens) < 2:
        return False
    if tokens[0].lower() in _HEADER_LABELS:
        return True
    return all(
        _NAME.match(token) and not token.endswith(":") for token in tokens
    )


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
