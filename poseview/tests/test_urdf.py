from __future__ import annotations

import math
import unittest

from poseview.urdf import UrdfError, parse_urdf_text

ARM = """<?xml version="1.0"?>
<robot name="arm">
  <link name="base"/>
  <link name="link1"/>
  <link name="link2"/>
  <link name="tool"/>
  <joint name="j1" type="revolute">
    <parent link="base"/>
    <child link="link1"/>
    <origin xyz="0 0 0.5" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.5708" upper="1.5708"/>
  </joint>
  <joint name="j2" type="revolute">
    <parent link="link1"/>
    <child link="link2"/>
    <origin xyz="1 0 0" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.5708" upper="1.5708"/>
  </joint>
  <joint name="j3" type="fixed">
    <parent link="link2"/>
    <child link="tool"/>
    <origin xyz="0.5 0 0" rpy="0 0 0"/>
  </joint>
</robot>
"""

PRISMATIC = """<robot name="slider">
  <link name="base"/>
  <link name="slider"/>
  <link name="tool"/>
  <joint name="push" type="prismatic">
    <parent link="base"/>
    <child link="slider"/>
    <axis xyz="1 0 0"/>
    <limit lower="0" upper="0.4"/>
  </joint>
  <joint name="attach" type="fixed">
    <parent link="slider"/>
    <child link="tool"/>
    <origin xyz="0.2 0 0"/>
  </joint>
</robot>
"""


class UrdfParseTests(unittest.TestCase):
    def test_tree(self):
        robot = parse_urdf_text(ARM)
        self.assertEqual(robot.name, "arm")
        self.assertEqual(robot.root_link, "base")
        self.assertEqual(robot.leaf_links, ["tool"])
        self.assertEqual([joint.name for joint in robot.movable_joints], ["j1", "j2"])
        self.assertEqual(robot.default_ee_link(), "tool")

    def test_default_values_clamp(self):
        robot = parse_urdf_text(ARM)
        values = robot.default_values()
        self.assertEqual(values, {"j1": 0.0, "j2": 0.0})

    def test_wrong_parent(self):
        text = ARM.replace('<parent link="base"/>', '<parent link="missing"/>')
        with self.assertRaises(UrdfError):
            parse_urdf_text(text)

    def test_cycle_rejected(self):
        text = """<robot name="loop">
          <link name="a"/><link name="b"/>
          <joint name="j1" type="fixed"><parent link="a"/><child link="b"/></joint>
          <joint name="j2" type="fixed"><parent link="b"/><child link="a"/></joint>
        </robot>"""
        with self.assertRaises(UrdfError):
            parse_urdf_text(text)

    def test_bad_xml(self):
        with self.assertRaises(UrdfError):
            parse_urdf_text("<robot><link name='a'></robot>")


class ForwardKinematicsTests(unittest.TestCase):
    def test_zero_pose(self):
        robot = parse_urdf_text(ARM)
        result = robot.forward(robot.default_values())
        self.assertEqual(result.ee_link, "tool")
        x, y, z = _translation(result.ee_matrix)
        self.assertAlmostEqual(x, 1.5, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.5, places=6)
        self.assertAlmostEqual(result.ee_matrix[0][0], 1.0, places=6)

    def test_first_joint_rotation(self):
        robot = parse_urdf_text(ARM)
        values = robot.default_values()
        values["j1"] = math.radians(90.0)
        result = robot.forward(values)
        x, y, z = _translation(result.ee_matrix)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 1.5, places=6)
        self.assertAlmostEqual(z, 0.5, places=6)
        self.assertAlmostEqual(result.ee_matrix[0][0], 0.0, places=6)
        self.assertAlmostEqual(result.ee_matrix[1][0], 1.0, places=6)

    def test_second_joint_rotation(self):
        robot = parse_urdf_text(ARM)
        values = robot.default_values()
        values["j2"] = math.radians(90.0)
        result = robot.forward(values)
        x, y, z = _translation(result.ee_matrix)
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 0.5, places=6)
        self.assertAlmostEqual(z, 0.5, places=6)

    def test_fixed_joint_origin_rpy(self):
        text = ARM.replace(
            '<origin xyz="0.5 0 0" rpy="0 0 0"/>',
            '<origin xyz="0.5 0 0" rpy="0 0 1.5708"/>',
        )
        robot = parse_urdf_text(text)
        result = robot.forward(robot.default_values())
        x, y, z = _translation(result.ee_matrix)
        self.assertAlmostEqual(x, 1.5, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(result.ee_matrix[1][0], 1.0, places=4)

    def test_prismatic(self):
        robot = parse_urdf_text(PRISMATIC)
        values = robot.default_values()
        result = robot.forward(values)
        self.assertAlmostEqual(_translation(result.ee_matrix)[0], 0.2, places=6)
        values["push"] = 0.3
        result = robot.forward(values)
        self.assertAlmostEqual(_translation(result.ee_matrix)[0], 0.5, places=6)

    def test_segments_and_joints(self):
        robot = parse_urdf_text(ARM)
        result = robot.forward(robot.default_values())
        self.assertEqual(len(result.segments), 3)
        self.assertEqual(len(result.joint_positions), 4)


def _translation(matrix):
    return (matrix[0][3], matrix[1][3], matrix[2][3])


if __name__ == "__main__":
    unittest.main()
