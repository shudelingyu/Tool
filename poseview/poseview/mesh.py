"""STL / OBJ 三角网格读取。"""

from __future__ import annotations

import struct
from pathlib import Path

Point = tuple[float, float, float]
Triangle = tuple[Point, Point, Point]


class MeshError(ValueError):
    """网格文件无法解析。"""


def load_triangles(path: Path) -> list[Triangle]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".stl":
            triangles = _load_stl(path)
        elif suffix == ".obj":
            triangles = _load_obj(path)
        else:
            raise MeshError(f"暂不支持 {suffix or '未知'} 网格格式")
    except OSError as exc:
        raise MeshError(f"无法读取网格：{exc}") from exc
    if not triangles:
        raise MeshError("网格中没有三角形")
    return triangles


def _load_stl(path: Path) -> list[Triangle]:
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        expected = 84 + count * 50
        if count > 0 and len(data) >= expected:
            triangles: list[Triangle] = []
            for index in range(count):
                offset = 84 + index * 50
                values = struct.unpack_from("<12f", data, offset)
                triangles.append(
                    (
                        (values[3], values[4], values[5]),
                        (values[6], values[7], values[8]),
                        (values[9], values[10], values[11]),
                    )
                )
            return triangles

    text = data.decode("utf-8", errors="ignore")
    vertices: list[Point] = []
    triangles = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            try:
                vertices.append(
                    (float(parts[1]), float(parts[2]), float(parts[3]))
                )
            except ValueError:
                continue
            if len(vertices) == 3:
                triangles.append((vertices[0], vertices[1], vertices[2]))
                vertices = []
    return triangles


def _load_obj(path: Path) -> list[Triangle]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    vertices: list[Point] = []
    triangles: list[Triangle] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            try:
                vertices.append(
                    (float(parts[1]), float(parts[2]), float(parts[3]))
                )
            except ValueError:
                continue
        elif parts[0] == "f" and len(parts) >= 4:
            indices = []
            for token in parts[1:]:
                raw = token.split("/")[0]
                try:
                    index = int(raw)
                except ValueError:
                    continue
                if index < 0:
                    index = len(vertices) + index
                else:
                    index -= 1
                if 0 <= index < len(vertices):
                    indices.append(index)
            for offset in range(1, len(indices) - 1):
                triangles.append(
                    (
                        vertices[indices[0]],
                        vertices[indices[offset]],
                        vertices[indices[offset + 1]],
                    )
                )
    return triangles
