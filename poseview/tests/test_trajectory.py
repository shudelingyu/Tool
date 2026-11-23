from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from poseview.trajectory import (
    TrajectoryError,
    frame_values,
    load_trajectory,
    resolve_mapping,
    trajectory_joints,
)
from poseview.urdf import parse_urdf_text

ARM = """<robot name="arm">
  <link name="base"/>
  <link name="link1"/>
  <link name="link2"/>
  <joint name="j1" type="revolute">
    <parent link="base"/><child link="link1"/>
    <axis xyz="0 0 1"/><limit lower="-3.1" upper="3.1"/>
  </joint>
  <joint name="j2" type="revolute">
    <parent link="link1"/><child link="link2"/>
    <origin xyz="0.5 0 0"/><axis xyz="0 0 1"/>
    <limit lower="-3.1" upper="3.1"/>
  </joint>
</robot>"""

NAMED = """<robot name="arm">
  <link name="base"/>
  <link name="link1"/>
  <link name="link2"/>
  <joint name="shoulder" type="revolute">
    <parent link="base"/><child link="link1"/>
    <axis xyz="0 0 1"/><limit lower="-3.1" upper="3.1"/>
  </joint>
  <joint name="elbow" type="prismatic">
    <parent link="link1"/><child link="link2"/>
    <axis xyz="1 0 0"/><limit lower="0" upper="0.4"/>
  </joint>
</robot>"""

MIMIC = """<robot name="gripper">
  <link name="base"/>
  <link name="left"/>
  <link name="right"/>
  <joint name="left_finger" type="prismatic">
    <parent link="base"/><child link="left"/>
    <axis xyz="1 0 0"/><limit lower="0" upper="0.05"/>
  </joint>
  <joint name="right_finger" type="prismatic">
    <parent link="base"/><child link="right"/>
    <origin xyz="0.05 0 0"/><axis xyz="-1 0 0"/>
    <limit lower="0" upper="0.05"/>
    <mimic joint="left_finger" multiplier="1" offset="0"/>
  </joint>
</robot>"""


class TrajectoryParseTests(unittest.TestCase):
    def _write(self, text: str, name: str = "trajectory.cst") -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_cst_header_and_prefix(self):
        path = self._write(
            "name J1 J2\n"
            "actpos: 0.1 0.2\n"
            "actpos: 0.3 0.4\n"
        )
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.columns, ["J1", "J2"])
        self.assertEqual(trajectory.frames, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(trajectory.labels, ["actpos", "actpos"])
        self.assertEqual(trajectory.frame_count, 2)
        self.assertEqual(trajectory.column_count, 2)

    def test_csv_numeric_rows(self):
        path = self._write(
            "J1,J2\n0.1,0.2\n0.3,0.4\n", "trajectory.csv"
        )
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.columns, ["J1", "J2"])
        self.assertEqual(trajectory.frames, [[0.1, 0.2], [0.3, 0.4]])

    def test_numeric_without_header(self):
        path = self._write("0.1\t0.2\n0.3\t0.4\n", "trajectory.txt")
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.columns, [])
        self.assertEqual(trajectory.frames, [[0.1, 0.2], [0.3, 0.4]])

    def test_bad_row_skipped(self):
        path = self._write(
            "name J1 J2\n"
            "actpos: 0.1 0.2\n"
            "actpos: 0.3 0.4 0.5\n"
            "actpos: 0.6 0.7\n"
        )
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.frames, [[0.1, 0.2], [0.6, 0.7]])
        self.assertTrue(any("不一致" in warning for warning in trajectory.warnings))

    def test_comment_and_empty_lines(self):
        path = self._write(
            "# comment\n"
            "\n"
            "name J1 J2\n"
            "// another comment\n"
            "actpos: 0.1 0.2\n"
        )
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.frames, [[0.1, 0.2]])

    def test_utf16_bom(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "utf16.cst"
        path.write_text(
            "name J1 J2\nactpos: 0.1 0.2\n", encoding="utf-16"
        )
        trajectory = load_trajectory(path)
        self.assertEqual(trajectory.columns, ["J1", "J2"])
        self.assertEqual(trajectory.frames, [[0.1, 0.2]])

    def test_no_data_raises(self):
        path = self._write("name J1 J2\n# no frames\n")
        with self.assertRaises(TrajectoryError):
            load_trajectory(path)


class MappingTests(unittest.TestCase):
    def test_alias_by_index(self):
        robot = parse_urdf_text(ARM)
        mapping, warnings = resolve_mapping(
            ["J1", "J2"], trajectory_joints(robot)
        )
        self.assertEqual(mapping, [0, 1])
        self.assertEqual(warnings, [])

    def test_alias_reordered(self):
        robot = parse_urdf_text(ARM)
        mapping, _warnings = resolve_mapping(
            ["J2", "J1"], trajectory_joints(robot)
        )
        self.assertEqual(mapping, [1, 0])

    def test_mapping_by_joint_name(self):
        robot = parse_urdf_text(NAMED)
        mapping, warnings = resolve_mapping(
            ["elbow", "shoulder"], trajectory_joints(robot)
        )
        self.assertEqual(mapping, [1, 0])
        self.assertEqual(warnings, [])

    def test_unmatched_and_order_mode(self):
        robot = parse_urdf_text(NAMED)
        mapping, warnings = resolve_mapping(
            ["alpha", "beta"], trajectory_joints(robot)
        )
        self.assertEqual(mapping, [None, None])
        self.assertEqual(len(warnings), 2)
        ordered, _warnings = resolve_mapping(
            ["alpha", "beta"], trajectory_joints(robot), mode="order"
        )
        self.assertEqual(ordered, [0, 1])

    def test_no_header_uses_order(self):
        robot = parse_urdf_text(ARM)
        mapping, _warnings = resolve_mapping([], trajectory_joints(robot))
        self.assertEqual(mapping, [0, 1])

    def test_column_count_without_header(self):
        robot = parse_urdf_text(ARM)
        mapping, _warnings = resolve_mapping(
            [], trajectory_joints(robot), column_count=1
        )
        self.assertEqual(mapping, [0])
        mapping, _warnings = resolve_mapping(
            [], trajectory_joints(robot), column_count=3
        )
        self.assertEqual(mapping, [0, 1, None])

    def test_mimic_excluded(self):
        robot = parse_urdf_text(MIMIC)
        names = [joint.name for joint in trajectory_joints(robot)]
        self.assertEqual(names, ["left_finger"])


class FrameValueTests(unittest.TestCase):
    def test_radians(self):
        robot = parse_urdf_text(ARM)
        values = frame_values(
            robot,
            [0.2, -0.4],
            [0, 1],
            {"j1": 0.0, "j2": 0.0},
        )
        self.assertAlmostEqual(values["j1"], 0.2)
        self.assertAlmostEqual(values["j2"], -0.4)

    def test_degrees_only_for_angular(self):
        robot = parse_urdf_text(NAMED)
        values = frame_values(
            robot,
            [90.0, 0.25],
            [0, 1],
            {"shoulder": 0.0, "elbow": 0.0},
            degrees=True,
        )
        self.assertAlmostEqual(values["shoulder"], math.pi / 2.0)
        self.assertAlmostEqual(values["elbow"], 0.25)

    def test_unmapped_columns_keep_base_values(self):
        robot = parse_urdf_text(ARM)
        values = frame_values(
            robot,
            [0.25, 0.3],
            [None, 0],
            {"j1": 0.9, "j2": 0.1},
        )
        self.assertAlmostEqual(values["j1"], 0.3)
        self.assertAlmostEqual(values["j2"], 0.1)

    def test_mimic_follows_source(self):
        robot = parse_urdf_text(MIMIC)
        values = frame_values(
            robot,
            [0.03],
            [0],
            {"left_finger": 0.0, "right_finger": 0.0},
        )
        self.assertAlmostEqual(values["left_finger"], 0.03)
        self.assertAlmostEqual(values["right_finger"], 0.03)


if __name__ == "__main__":
    unittest.main()
