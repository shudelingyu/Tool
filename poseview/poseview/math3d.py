"""位姿矩阵解析与姿态解算。

矩阵约定：T = [[R, t], [0, 1]]，右手坐标系，Z 轴向上。
支持 3x3（仅旋转）、3x4、4x4 输入，可一次输入多帧。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_BLANK_RE = re.compile(r"\n\s*\n")
_SEPARATOR_CHARS = {"-", "=", "*", "_"}


class MatrixParseError(ValueError):
    """输入无法解析为位姿矩阵。"""


@dataclass
class PoseValues:
    position: tuple[float, float, float]
    roll: float
    pitch: float
    yaw: float
    quaternion: tuple[float, float, float, float]
    rotation: list[list[float]]
    orthonormal: bool = True

    def report(self, name: str = "") -> str:
        lines: list[str] = []
        if name:
            lines.append(name)
        x, y, z = self.position
        lines.append(
            "position (m): x={} y={} z={}".format(
                format_number(x, 6), format_number(y, 6), format_number(z, 6)
            )
        )
        lines.append(
            "rpy (deg): roll={} pitch={} yaw={}".format(
                format_number(self.roll, 4),
                format_number(self.pitch, 4),
                format_number(self.yaw, 4),
            )
        )
        lines.append(
            "quaternion (w,x,y,z): " + ", ".join(format_number(v, 6) for v in self.quaternion)
        )
        lines.append("rotation:")
        for row in self.rotation:
            lines.append("  " + "  ".join(format_number(v, 6).rjust(11) for v in row))
        return "\n".join(lines)


@dataclass
class Pose:
    matrix: list[list[float]]
    values: PoseValues = field(init=False)

    def __post_init__(self) -> None:
        self.values = pose_values(self.matrix)

    def matrix_text(self, digits: int = 6) -> str:
        return "\n".join(
            "  ".join(format_number(value, digits).rjust(11) for value in row)
            for row in self.matrix
        )


def format_number(value: float, digits: int = 6) -> str:
    if abs(value) < 0.5 * 10 ** (-digits):
        value = 0.0
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    return text


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def parse_poses(text: str, mode: str = "matrix") -> list[Pose]:
    if mode == "quat":
        return _parse_fixed_blocks(
            text,
            7,
            _pose_from_position_quaternion,
            "位置 + 四元数每帧需要 7 个数字（x y z qw qx qy qz）",
        )
    if mode == "euler":
        return _parse_fixed_blocks(
            text,
            6,
            _pose_from_position_euler,
            "位置 + 欧拉角每帧需要 6 个数字（x y z roll pitch yaw，度）",
        )
    if mode == "rotvec":
        return _parse_fixed_blocks(
            text,
            6,
            _pose_from_position_rotation_vector,
            "位置 + 旋转向量每帧需要 6 个数字（x y z rx ry rz，弧度）",
        )
    matrices = parse_matrices(text)
    return [Pose(matrix) for matrix in matrices]


def parse_vectors(
    text: str, mode: str = "direction"
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """解析向量输入，返回 (起点, 方向) 列表。

    每行 6 个数：起点 x y z + 方向 x y z；mode="end" 时后三个数为终点。
    """
    if not text or not text.strip():
        raise MatrixParseError("请输入向量数据")

    vectors: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    use_end = mode == "end"
    for index, block in enumerate(_split_blocks(text), start=1):
        numbers = _numbers(block)
        if not numbers:
            continue
        if len(numbers) % 6 != 0:
            raise MatrixParseError(
                f"第 {index} 段共 {len(numbers)} 个数字，向量每行需要 6 个数字"
                "（起点 x y z + 方向/终点 x y z）"
            )
        for offset in range(0, len(numbers), 6):
            start = (numbers[offset], numbers[offset + 1], numbers[offset + 2])
            second = numbers[offset + 3 : offset + 6]
            if use_end:
                direction = tuple(second[i] - start[i] for i in range(3))
                if vector_length(direction) < 1e-9:
                    raise MatrixParseError("起点与终点重合，无法构成向量")
            else:
                direction = (second[0], second[1], second[2])
                if vector_length(direction) < 1e-9:
                    raise MatrixParseError("向量方向为零向量")
            vectors.append((start, direction))
    if not vectors:
        raise MatrixParseError("没有识别到向量数据")
    return vectors


def parse_matrices(text: str) -> list[list[list[float]]]:
    if not text or not text.strip():
        raise MatrixParseError("请输入位姿矩阵")

    matrices: list[list[list[float]]] = []
    blocks = _split_blocks(text)
    for index, block in enumerate(blocks, start=1):
        numbers = _numbers(block)
        if not numbers:
            continue
        chunk = _chunk_size(len(numbers))
        if chunk is None:
            raise MatrixParseError(
                f"第 {index} 段共 {len(numbers)} 个数字，无法组成 3x3 / 3x4 / 4x4 矩阵"
            )
        for offset in range(0, len(numbers), chunk):
            matrices.append(_build_matrix(numbers[offset : offset + chunk]))
    if not matrices:
        raise MatrixParseError("没有识别到矩阵数字")
    return matrices


def _split_blocks(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "//")):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)

    blocks: list[str] = []
    for part in _BLANK_RE.split(cleaned):
        chunk: list[str] = []
        for line in part.splitlines():
            stripped = line.strip()
            if (
                len(stripped) >= 3
                and set(stripped) <= _SEPARATOR_CHARS
            ):
                if chunk:
                    blocks.append("\n".join(chunk))
                    chunk = []
                continue
            chunk.append(line)
        if chunk:
            blocks.append("\n".join(chunk))
    return [block for block in blocks if block.strip()]


def _numbers(text: str) -> list[float]:
    values = []
    for match in _NUMBER_RE.finditer(text):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return values


def _chunk_size(count: int) -> int | None:
    if count >= 16 and count % 16 == 0:
        return 16
    if count >= 12 and count % 12 == 0:
        return 12
    if count >= 9 and count % 9 == 0:
        return 9
    return None


def _build_matrix(values: list[float]) -> list[list[float]]:
    if len(values) == 16:
        matrix = [values[row * 4 : row * 4 + 4] for row in range(4)]
        if any(abs(matrix[3][i] - target) > 1e-4 for i, target in enumerate((0.0, 0.0, 0.0, 1.0))):
            raise MatrixParseError("4x4 矩阵最后一行应为 0 0 0 1")
        return matrix
    if len(values) == 12:
        rows = [values[row * 4 : row * 4 + 4] for row in range(3)]
        rows.append([0.0, 0.0, 0.0, 1.0])
        return rows
    if len(values) == 9:
        rows = [values[row * 3 : row * 3 + 3] for row in range(3)]
        return [
            [rows[0][0], rows[0][1], rows[0][2], 0.0],
            [rows[1][0], rows[1][1], rows[1][2], 0.0],
            [rows[2][0], rows[2][1], rows[2][2], 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    raise MatrixParseError("矩阵尺寸不受支持")


def _parse_fixed_blocks(text: str, size: int, builder, hint: str) -> list[Pose]:
    if not text or not text.strip():
        raise MatrixParseError("请输入位姿数据")
    poses: list[Pose] = []
    for index, block in enumerate(_split_blocks(text), start=1):
        numbers = _numbers(block)
        if not numbers:
            continue
        if len(numbers) % size != 0:
            raise MatrixParseError(f"第 {index} 段共 {len(numbers)} 个数字，{hint}")
        for offset in range(0, len(numbers), size):
            poses.append(builder(numbers[offset : offset + size]))
    if not poses:
        raise MatrixParseError("没有识别到位姿数据")
    return poses


def _pose_from_position_quaternion(values: list[float]) -> Pose:
    x, y, z, qw, qx, qy, qz = values
    rotation = rotation_from_quaternion(qw, qx, qy, qz)
    return Pose(_assemble_matrix(rotation, (x, y, z)))


def _pose_from_position_euler(values: list[float]) -> Pose:
    x, y, z, roll, pitch, yaw = values
    rotation = rotation_from_euler(roll, pitch, yaw)
    return Pose(_assemble_matrix(rotation, (x, y, z)))


def _pose_from_position_rotation_vector(values: list[float]) -> Pose:
    x, y, z, rx, ry, rz = values
    rotation = rotation_from_rotation_vector(rx, ry, rz)
    return Pose(_assemble_matrix(rotation, (x, y, z)))


def _assemble_matrix(
    rotation: list[list[float]], position: tuple[float, float, float]
) -> list[list[float]]:
    return [
        [rotation[0][0], rotation[0][1], rotation[0][2], position[0]],
        [rotation[1][0], rotation[1][1], rotation[1][2], position[1]],
        [rotation[2][0], rotation[2][1], rotation[2][2], position[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


# ---------------------------------------------------------------------------
# 姿态解算
# ---------------------------------------------------------------------------


def rotation_from_quaternion(w: float, x: float, y: float, z: float) -> list[list[float]]:
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-9:
        raise MatrixParseError("四元数模长为 0，无法确定姿态")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return [
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ]


def rotation_from_euler(roll: float, pitch: float, yaw: float) -> list[list[float]]:
    rx, ry, rz = map(math.radians, (roll, pitch, yaw))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def rotation_from_rotation_vector(
    rx: float, ry: float, rz: float
) -> list[list[float]]:
    """由旋转向量（轴 × 弧度）构造旋转矩阵（Rodrigues 公式）。"""
    angle = math.sqrt(rx * rx + ry * ry + rz * rz)
    if angle < 1e-12:
        return _identity_rotation()
    kx, ky, kz = rx / angle, ry / angle, rz / angle
    c, s = math.cos(angle), math.sin(angle)
    v = 1.0 - c
    return [
        [c + kx * kx * v, kx * ky * v - kz * s, kx * kz * v + ky * s],
        [ky * kx * v + kz * s, c + ky * ky * v, ky * kz * v - kx * s],
        [kz * kx * v - ky * s, kz * ky * v + kx * s, c + kz * kz * v],
    ]


def axis_angle_from_rotation(
    rotation: list[list[float]],
) -> tuple[tuple[float, float, float], float]:
    """由旋转矩阵求单位转轴与角度（度）。零旋转返回 X 轴、0°。"""
    w, x, y, z = quaternion_from_rotation(rotation)
    sin_half = math.sqrt(x * x + y * y + z * z)
    if sin_half < 1e-12:
        return (1.0, 0.0, 0.0), 0.0
    angle = math.degrees(2.0 * math.atan2(sin_half, w))
    return (x / sin_half, y / sin_half, z / sin_half), angle


def rotation_vector_from_rotation(
    rotation: list[list[float]],
) -> tuple[float, float, float]:
    """由旋转矩阵求旋转向量（轴 × 弧度）。"""
    axis, angle = axis_angle_from_rotation(rotation)
    radians = math.radians(angle)
    return (axis[0] * radians, axis[1] * radians, axis[2] * radians)


def transform_point(
    matrix: list[list[float]], point: tuple[float, float, float]
) -> tuple[float, float, float]:
    """用齐次变换矩阵变换点：p' = R·p + t。"""
    return tuple(
        matrix[row][0] * point[0]
        + matrix[row][1] * point[1]
        + matrix[row][2] * point[2]
        + matrix[row][3]
        for row in range(3)
    )


def transform_vector(
    matrix: list[list[float]], vector: tuple[float, float, float]
) -> tuple[float, float, float]:
    """用齐次变换矩阵变换方向向量：v' = R·v。"""
    return tuple(
        matrix[row][0] * vector[0]
        + matrix[row][1] * vector[1]
        + matrix[row][2] * vector[2]
        for row in range(3)
    )


def matrix_properties(
    matrix: list[list[float]],
) -> tuple[float, float, float]:
    """返回 (旋转部分行列式, 正交误差, 迹)。"""
    rotation = [row[:3] for row in matrix[:3]]
    determinant = (
        rotation[0][0]
        * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1]
        * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2]
        * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    error = 0.0
    for i in range(3):
        for j in range(3):
            dot = sum(rotation[k][i] * rotation[k][j] for k in range(3))
            target = 1.0 if i == j else 0.0
            error = max(error, abs(dot - target))
    trace = rotation[0][0] + rotation[1][1] + rotation[2][2]
    return determinant, error, trace


def quaternion_multiply(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    w1, x1, y1, z1 = first
    w2, x2, y2, z2 = second
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def quaternion_conjugate(
    quaternion: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    w, x, y, z = quaternion
    return (w, -x, -y, -z)


def slerp_quaternion(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    """四元数球面插值（取最短路径）。"""
    t = max(0.0, min(1.0, t))
    dot = sum(a * b for a, b in zip(first, second))
    if dot < 0.0:
        second = tuple(-value for value in second)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        result = tuple(first[i] + (second[i] - first[i]) * t for i in range(4))
        length = math.sqrt(sum(value * value for value in result))
        if length < 1e-12:
            return first
        return tuple(value / length for value in result)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    weight_first = math.sin((1.0 - t) * theta) / sin_theta
    weight_second = math.sin(t * theta) / sin_theta
    return tuple(
        first[i] * weight_first + second[i] * weight_second for i in range(4)
    )


def vector_cross(first, second) -> tuple[float, float, float]:
    """两个三维向量的叉积。"""
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def project_vector(first, second) -> tuple[float, float, float]:
    """向量 first 在 second 上的投影。"""
    length_sq = sum(value * value for value in second)
    if length_sq < 1e-18:
        return (0.0, 0.0, 0.0)
    scale = sum(a * b for a, b in zip(first, second)) / length_sq
    return (second[0] * scale, second[1] * scale, second[2] * scale)


def solve_linear(
    matrix: list[list[float]], vector: list[float]
) -> list[float] | None:
    """高斯-约当消元求解 A·x = b，奇异时返回 None。"""
    size = len(vector)
    augmented = [
        [float(value) for value in matrix[row]] + [float(vector[row])]
        for row in range(size)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        if pivot != column:
            augmented[column], augmented[pivot] = (
                augmented[pivot],
                augmented[column],
            )
        divisor = augmented[column][column]
        for index in range(column, size + 1):
            augmented[column][index] /= divisor
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) < 1e-15:
                continue
            for index in range(column, size + 1):
                augmented[row][index] -= factor * augmented[column][index]
    return [augmented[row][size] for row in range(size)]


def pose_values(matrix: list[list[float]]) -> PoseValues:
    rotation, orthonormal = _orthonormalize([row[:3] for row in matrix[:3]])
    quaternion = quaternion_from_rotation(rotation)
    roll, pitch, yaw = euler_zyx_deg(rotation)
    return PoseValues(
        position=(matrix[0][3], matrix[1][3], matrix[2][3]),
        roll=roll,
        pitch=pitch,
        yaw=yaw,
        quaternion=quaternion,
        rotation=rotation,
        orthonormal=orthonormal,
    )


def multiply_transform(
    first: list[list[float]], second: list[list[float]]
) -> list[list[float]]:
    return [
        [
            sum(first[row][k] * second[k][col] for k in range(4))
            for col in range(4)
        ]
        for row in range(4)
    ]


def invert_transform(matrix: list[list[float]]) -> list[list[float]]:
    """求齐次变换逆：T⁻¹ = [Rᵀ, -Rᵀt; 0, 1]。"""
    rotation = [[matrix[row][col] for col in range(3)] for row in range(3)]
    translation = [matrix[0][3], matrix[1][3], matrix[2][3]]
    transposed = [[rotation[col][row] for col in range(3)] for row in range(3)]
    inverse_translation = [
        -sum(transposed[row][k] * translation[k] for k in range(3))
        for row in range(3)
    ]
    return [
        [transposed[0][0], transposed[0][1], transposed[0][2], inverse_translation[0]],
        [transposed[1][0], transposed[1][1], transposed[1][2], inverse_translation[1]],
        [transposed[2][0], transposed[2][1], transposed[2][2], inverse_translation[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def relative_transform(
    base: list[list[float]], target: list[list[float]]
) -> list[list[float]]:
    """计算 target 在 base 坐标系下的位姿：inv(T_base) · T_target。"""
    return multiply_transform(invert_transform(base), target)


def rotation_angle_between(
    first: list[list[float]], second: list[list[float]]
) -> float:
    """两个旋转矩阵之间的夹角（度）。"""
    trace = sum(first[k][i] * second[k][i] for i in range(3) for k in range(3))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return math.degrees(math.acos(cosine))


def vector_length(vector) -> float:
    return math.sqrt(sum(value * value for value in vector))


def angle_between_vectors(first, second) -> float:
    """两个三维向量的夹角（度，0~180）。"""
    length_first = vector_length(first)
    length_second = vector_length(second)
    if length_first < 1e-12 or length_second < 1e-12:
        raise MatrixParseError("存在零向量，无法计算夹角")
    cosine = sum(a * b for a, b in zip(first, second)) / (length_first * length_second)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def vector_dot(first, second) -> float:
    return sum(a * b for a, b in zip(first, second))


def quaternion_from_rotation(rotation: list[list[float]]) -> tuple[float, float, float, float]:
    r = rotation
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2][1] - r[1][2]) / s
        y = (r[0][2] - r[2][0]) / s
        z = (r[1][0] - r[0][1]) / s
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2.0
        w = (r[2][1] - r[1][2]) / s
        x = 0.25 * s
        y = (r[0][1] + r[1][0]) / s
        z = (r[0][2] + r[2][0]) / s
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2.0
        w = (r[0][2] - r[2][0]) / s
        x = (r[0][1] + r[1][0]) / s
        y = 0.25 * s
        z = (r[1][2] + r[2][1]) / s
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2.0
        w = (r[1][0] - r[0][1]) / s
        x = (r[0][2] + r[2][0]) / s
        y = (r[1][2] + r[2][1]) / s
        z = 0.25 * s

    length = math.sqrt(w * w + x * x + y * y + z * z)
    if length > 1e-12:
        w, x, y, z = w / length, x / length, y / length, z / length
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    return (w, x, y, z)


def euler_zyx_deg(rotation: list[list[float]]) -> tuple[float, float, float]:
    r = rotation
    sin_pitch = max(-1.0, min(1.0, -r[2][0]))
    pitch = math.asin(sin_pitch)
    if abs(math.cos(pitch)) > 1e-6:
        roll = math.atan2(r[2][1], r[2][2])
        yaw = math.atan2(r[1][0], r[0][0])
    else:
        roll = math.atan2(-r[1][2], r[1][1])
        yaw = 0.0
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


def _orthonormalize(rotation: list[list[float]]) -> tuple[list[list[float]], bool]:
    columns = _columns(rotation)
    x = columns[0]
    nx = _norm(x)
    if nx < 1e-12:
        return _identity_rotation(), False
    x = [value / nx for value in x]

    y = columns[1]
    projection = _dot(x, y)
    y = [y[i] - x[i] * projection for i in range(3)]
    ny = _norm(y)
    if ny < 1e-12:
        return _identity_rotation(), False
    y = [value / ny for value in y]

    z = _cross(x, y)
    used = _from_columns([x, y, z])

    deviation = 0.0
    for i in range(3):
        for j in range(3):
            target = 1.0 if i == j else 0.0
            deviation = max(deviation, abs(_dot(columns[i], columns[j]) - target))
    return used, deviation <= 1e-4


def _identity_rotation() -> list[list[float]]:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def _columns(matrix: list[list[float]]) -> list[list[float]]:
    return [[matrix[row][col] for row in range(3)] for col in range(3)]


def _from_columns(columns: list[list[float]]) -> list[list[float]]:
    return [[columns[col][row] for col in range(3)] for row in range(3)]


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _norm(vector: list[float]) -> float:
    return math.sqrt(_dot(vector, vector))
