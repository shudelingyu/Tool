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

MIMIC = """<robot name="gripper">
  <link name="base"/>
  <link name="left"/>
  <link name="right"/>
  <joint name="left_finger" type="prismatic">
    <parent link="base"/>
    <child link="left"/>
    <axis xyz="1 0 0"/>
    <limit lower="0" upper="0.05"/>
  </joint>
  <joint name="right_finger" type="prismatic">
    <parent link="base"/>
    <child link="right"/>
    <origin xyz="0.05 0 0"/>
    <axis xyz="-1 0 0"/>
    <limit lower="0" upper="0.05"/>
    <mimic joint="left_finger" multiplier="1" offset="0"/>
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

    def test_joint_frames(self):
        robot = parse_urdf_text(ARM)
        result = robot.forward(robot.default_values())
        self.assertEqual(set(result.joint_frames), {"j1", "j2", "j3"})
        for name, expected in (
            ("j1", (0.0, 0.0, 0.5)),
            ("j2", (1.0, 0.0, 0.5)),
            ("j3", (1.5, 0.0, 0.5)),
        ):
            actual = _translation(result.joint_frames[name])
            for value, target in zip(actual, expected):
                self.assertAlmostEqual(value, target, places=6)


VISUAL_BOX = """<robot name="boxy">
  <material name="blue"><color rgba="0.1 0.2 0.8 1.0"/></material>
  <link name="base">
    <visual>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <geometry><box size="1 2 3"/></geometry>
      <material name="blue"/>
    </visual>
  </link>
  <link name="tool"/>
  <joint name="fix" type="fixed">
    <parent link="base"/>
    <child link="tool"/>
  </joint>
</robot>"""


class VisualTests(unittest.TestCase):
    def test_box_visual_triangles(self):
        robot = parse_urdf_text(VISUAL_BOX)
        self.assertEqual(len(robot.visuals), 1)
        visual = robot.visuals[0]
        self.assertEqual(visual.link, "base")
        self.assertEqual(len(visual.triangles), 12)
        self.assertAlmostEqual(visual.color[2], 0.8, places=6)
        xs = [vertex[0] for tri in visual.triangles for vertex in tri]
        zs = [vertex[2] for tri in visual.triangles for vertex in tri]
        self.assertAlmostEqual(min(xs), -0.5, places=6)
        self.assertAlmostEqual(max(xs), 0.5, places=6)
        self.assertAlmostEqual(min(zs), -1.5, places=6)
        self.assertAlmostEqual(max(zs), 1.5, places=6)

    def test_mesh_missing_file_warns(self):
        text = """<robot name="meshy">
          <link name="base">
            <visual>
              <geometry><mesh filename="missing.stl"/></geometry>
            </visual>
          </link>
          <link name="tool"/>
          <joint name="fix" type="fixed">
            <parent link="base"/>
            <child link="tool"/>
          </joint>
        </robot>"""
        robot = parse_urdf_text(text)
        self.assertEqual(robot.visuals, [])
        self.assertTrue(robot.warnings)


class InverseKinematicsTests(unittest.TestCase):
    def test_solve_reaches_target(self):
        robot = parse_urdf_text(ARM)
        goal = robot.default_values()
        goal["j1"] = math.radians(35.0)
        goal["j2"] = math.radians(-55.0)
        target = robot.forward(goal).ee_matrix
        result = robot.solve_ik(robot.default_values(), "tool", target)
        self.assertTrue(result.success)
        self.assertLess(result.position_error, 1e-3)
        actual = _translation(robot.forward(result.values).ee_matrix)
        for value, expected in zip(actual, _translation(target)):
            self.assertAlmostEqual(value, expected, places=3)

    def test_locked_joint_unchanged(self):
        robot = parse_urdf_text(ARM)
        goal = robot.default_values()
        goal["j1"] = math.radians(25.0)
        goal["j2"] = math.radians(40.0)
        target = robot.forward(goal).ee_matrix
        result = robot.solve_ik(
            robot.default_values(), "tool", target, locked={"j2"}
        )
        self.assertAlmostEqual(result.values["j2"], 0.0, places=6)


class MimicTests(unittest.TestCase):
    def test_mimic_follows_source(self):
        robot = parse_urdf_text(MIMIC)
        values = robot.default_values()
        values["left_finger"] = 0.02
        result = robot.forward(values)
        self.assertAlmostEqual(result.link_frames["left"][0][3], 0.02, places=6)
        self.assertAlmostEqual(result.link_frames["right"][0][3], 0.03, places=6)
        joint = next(item for item in result.joint_infos if item.name == "right_finger")
        self.assertAlmostEqual(joint.value, 0.02, places=6)

    def test_mimic_multiplier_offset(self):
        text = MIMIC.replace('multiplier="1" offset="0"', 'multiplier="-0.5" offset="-0.01"')
        robot = parse_urdf_text(text)
        values = robot.default_values()
        values["left_finger"] = 0.02
        result = robot.forward(values)
        self.assertAlmostEqual(result.link_frames["right"][0][3], 0.07, places=6)

    def test_mimic_missing_source(self):
        text = MIMIC.replace('joint="left_finger"', 'joint="missing"')
        robot = parse_urdf_text(text)
        self.assertTrue(any("mimic" in warning for warning in robot.warnings))
        joint = next(item for item in robot.joints if item.name == "right_finger")
        self.assertEqual(joint.mimic, "")

    def test_mimic_not_ik_variable(self):
        robot = parse_urdf_text(MIMIC)
        values = robot.default_values()
        values["left_finger"] = 0.02
        target = robot.forward(values).ee_matrix
        result = robot.solve_ik(
            robot.default_values(), "right", target, position_weight=1.0,
            orientation_weight=0.0,
        )
        self.assertEqual(result.values["right_finger"], 0.0)


def _translation(matrix):
    return (matrix[0][3], matrix[1][3], matrix[2][3])


if __name__ == "__main__":
    unittest.main()
