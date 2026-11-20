from __future__ import annotations

import math
import unittest

from poseview.math3d import (
    MatrixParseError,
    format_number,
    invert_transform,
    multiply_transform,
    parse_poses,
    pose_values,
    quaternion_from_rotation,
    relative_transform,
    rotation_angle_between,
)

IDENTITY = """1 0 0 0
0 1 0 0
0 0 1 0
0 0 0 1"""

YAW_90 = """0 -1 0 1.5
1 0 0 -2
0 0 1 0.5
0 0 0 1"""


def rotation_matrix(roll: float, pitch: float, yaw: float) -> list[list[float]]:
    rx, ry, rz = map(math.radians, (roll, pitch, yaw))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    x_axis = [cz * cy, sz * cy, -sy]
    y_axis = [cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx]
    z_axis = [cz * sy * cx + sz * sx, sz * sy * cx - cz * sx, cy * cx]
    return [
        [x_axis[0], y_axis[0], z_axis[0]],
        [x_axis[1], y_axis[1], z_axis[1]],
        [x_axis[2], y_axis[2], z_axis[2]],
    ]


class ParseTests(unittest.TestCase):
    def test_identity(self):
        poses = parse_poses(IDENTITY)
        self.assertEqual(len(poses), 1)
        values = poses[0].values
        self.assertEqual(values.position, (0.0, 0.0, 0.0))
        self.assertAlmostEqual(values.roll, 0.0)
        self.assertAlmostEqual(values.pitch, 0.0)
        self.assertAlmostEqual(values.yaw, 0.0)
        self.assertAlmostEqual(values.quaternion[0], 1.0)
        self.assertTrue(values.orthonormal)

    def test_yaw_90_with_translation(self):
        values = parse_poses(YAW_90)[0].values
        self.assertAlmostEqual(values.position[0], 1.5)
        self.assertAlmostEqual(values.position[1], -2.0)
        self.assertAlmostEqual(values.position[2], 0.5)
        self.assertAlmostEqual(values.yaw, 90.0)
        self.assertAlmostEqual(values.roll, 0.0)
        self.assertAlmostEqual(values.pitch, 0.0)
        w, x, y, z = values.quaternion
        self.assertAlmostEqual(w, math.sqrt(0.5), places=6)
        self.assertAlmostEqual(z, math.sqrt(0.5), places=6)

    def test_3x4(self):
        values = parse_poses("1 0 0 0.3\n0 1 0 0.4\n0 0 1 0.5")[0].values
        self.assertAlmostEqual(values.position[0], 0.3)
        self.assertAlmostEqual(values.position[1], 0.4)
        self.assertAlmostEqual(values.position[2], 0.5)
        self.assertAlmostEqual(values.yaw, 0.0)

    def test_3x3(self):
        text = "0 -1 0\n1 0 0\n0 0 1"
        values = parse_poses(text)[0].values
        self.assertEqual(values.position, (0.0, 0.0, 0.0))
        self.assertAlmostEqual(values.yaw, 90.0)

    def test_multiple_blocks(self):
        self.assertEqual(len(parse_poses(IDENTITY + "\n\n" + YAW_90)), 2)
        self.assertEqual(len(parse_poses(IDENTITY + "\n---\n" + YAW_90)), 2)

    def test_comma_and_bracket_tolerance(self):
        text = "[[0, -1, 0, 1.5], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]"
        values = parse_poses(text)[0].values
        self.assertAlmostEqual(values.yaw, 90.0)
        self.assertAlmostEqual(values.position[0], 1.5)

    def test_comment_lines_ignored(self):
        text = "# base pose\n" + IDENTITY
        self.assertEqual(len(parse_poses(text)), 1)

    def test_bad_bottom_row(self):
        text = "1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 2"
        with self.assertRaises(MatrixParseError):
            parse_poses(text)

    def test_wrong_number_count(self):
        with self.assertRaises(MatrixParseError):
            parse_poses("1 2 3")

    def test_empty_input(self):
        with self.assertRaises(MatrixParseError):
            parse_poses("   ")

    def test_non_orthonormal_rotation(self):
        text = "2 0 0 0\n0 2 0 0\n0 0 2 1\n0 0 0 1"
        values = parse_poses(text)[0].values
        self.assertFalse(values.orthonormal)
        self.assertAlmostEqual(values.rotation[0][0], 1.0)
        self.assertAlmostEqual(values.quaternion[0], 1.0)

    def test_euler_roundtrip(self):
        matrix = rotation_matrix(10.0, 20.0, 30.0)
        values = pose_values(
            [
                [matrix[0][0], matrix[0][1], matrix[0][2], 0.0],
                [matrix[1][0], matrix[1][1], matrix[1][2], 0.0],
                [matrix[2][0], matrix[2][1], matrix[2][2], 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        self.assertAlmostEqual(values.roll, 10.0, places=5)
        self.assertAlmostEqual(values.pitch, 20.0, places=5)
        self.assertAlmostEqual(values.yaw, 30.0, places=5)

        w, x, y, z = quaternion_from_rotation(matrix)
        self.assertAlmostEqual(math.sqrt(w * w + x * x + y * y + z * z), 1.0, places=9)

    def test_gimbal_lock(self):
        values = pose_values(
            [
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        self.assertAlmostEqual(values.pitch, 90.0, places=5)


class VectorInputTests(unittest.TestCase):
    def test_quaternion_identity(self):
        values = parse_poses("1 2 3   1 0 0 0", mode="quat")[0].values
        self.assertEqual(values.position, (1.0, 2.0, 3.0))
        self.assertAlmostEqual(values.yaw, 0.0)
        self.assertAlmostEqual(values.quaternion[0], 1.0)

    def test_quaternion_yaw_90(self):
        values = parse_poses("0 0 0   0.7071068 0 0 0.7071068", mode="quat")[0].values
        self.assertAlmostEqual(values.yaw, 90.0, places=5)
        self.assertAlmostEqual(values.roll, 0.0, places=5)
        self.assertAlmostEqual(values.pitch, 0.0, places=5)

    def test_quaternion_is_normalized(self):
        values = parse_poses("0 0 0   2 0 0 0", mode="quat")[0].values
        self.assertAlmostEqual(values.yaw, 0.0)
        self.assertAlmostEqual(values.quaternion[0], 1.0)
        self.assertTrue(values.orthonormal)

    def test_quaternion_zero_norm(self):
        with self.assertRaises(MatrixParseError):
            parse_poses("0 0 0   0 0 0 0", mode="quat")

    def test_quaternion_wrong_count(self):
        with self.assertRaises(MatrixParseError):
            parse_poses("0 0 0   1 0 0", mode="quat")

    def test_quaternion_multiple_frames(self):
        text = "0 0 0 1 0 0 0\n\n1 0 0 1 0 0 0"
        self.assertEqual(len(parse_poses(text, mode="quat")), 2)

    def test_euler_identity_with_position(self):
        values = parse_poses("1 2 3   0 0 0", mode="euler")[0].values
        self.assertEqual(values.position, (1.0, 2.0, 3.0))
        self.assertAlmostEqual(values.yaw, 0.0)
        self.assertAlmostEqual(values.rotation[0][0], 1.0)

    def test_euler_roundtrip(self):
        values = parse_poses("0 0 0   10 20 30", mode="euler")[0].values
        self.assertAlmostEqual(values.roll, 10.0, places=5)
        self.assertAlmostEqual(values.pitch, 20.0, places=5)
        self.assertAlmostEqual(values.yaw, 30.0, places=5)

    def test_euler_wrong_count(self):
        with self.assertRaises(MatrixParseError):
            parse_poses("0 0 0   0 0", mode="euler")

    def test_euler_multiple_frames(self):
        text = "0 0 0 0 0 0\n---\n1 0 0 0 0 45"
        poses = parse_poses(text, mode="euler")
        self.assertEqual(len(poses), 2)
        self.assertAlmostEqual(poses[1].values.yaw, 45.0, places=5)


class TransformTests(unittest.TestCase):
    def test_invert_roundtrip(self):
        matrix = [
            [0.0, -1.0, 0.0, 1.5],
            [1.0, 0.0, 0.0, -2.0],
            [0.0, 0.0, 1.0, 0.5],
            [0.0, 0.0, 0.0, 1.0],
        ]
        product = multiply_transform(matrix, invert_transform(matrix))
        for row in range(4):
            for col in range(4):
                target = 1.0 if row == col else 0.0
                self.assertAlmostEqual(product[row][col], target, places=9)

    def test_relative_translation(self):
        base = [
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        target = [
            [1.0, 0.0, 0.0, 3.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        relative = relative_transform(base, target)
        self.assertAlmostEqual(relative[0][3], 2.0)
        self.assertAlmostEqual(relative[1][3], 0.0)

    def test_relative_with_rotation(self):
        base = [
            [0.0, -1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        target = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 2.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        relative = relative_transform(base, target)
        self.assertAlmostEqual(relative[0][3], 2.0, places=9)
        self.assertAlmostEqual(relative[1][3], 0.0, places=9)

    def test_rotation_angle(self):
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        yaw_30 = rotation_matrix(0.0, 0.0, 30.0)
        self.assertAlmostEqual(rotation_angle_between(identity, yaw_30), 30.0, places=6)
        self.assertAlmostEqual(rotation_angle_between(identity, identity), 0.0, places=6)


class FormatTests(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(format_number(1.0), "1")
        self.assertEqual(format_number(-0.0000001), "0")
        self.assertEqual(format_number(0.123456, 2), "0.12")
        self.assertEqual(format_number(-2.5), "-2.5")


if __name__ == "__main__":
    unittest.main()
