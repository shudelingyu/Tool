#!/usr/bin/env python3
"""
verify_result.py
验证标定结果：对比标定前后末端位姿误差
"""

import numpy as np
import pinocchio as pin
import pandas as pd
import matplotlib.pyplot as plt


def load_measurements(csv_file):
    """加载测量数据"""
    df = pd.read_csv(csv_file)
    # 分离关节角度和位姿
    # 假设最后一列为marker_qz，往前数7列是位姿数据
    num_joints = df.shape[1] - 7
    joint_names = df.columns[:num_joints].tolist()
    q = df.iloc[:, :num_joints].values
    P = df.iloc[:, num_joints:].values  # [x, y, z, qw, qx, qy, qz]
    return q, P, joint_names


def compute_pose_error(robot, q, P_measured, end_frame_id):
    """计算位姿误差"""
    errors = []
    for i in range(q.shape[0]):
        pin.framesForwardKinematics(robot.model, robot.data, q[i, :])
        oMf = robot.data.oMf[end_frame_id]
        
        pred_pos = oMf.translation
        pred_rot = oMf.rotation
        
        meas_pos = P_measured[i, 0:3]
        meas_quat = P_measured[i, 3:7]
        meas_rot = pin.Quaternion(meas_quat[0], meas_quat[1], meas_quat[2], meas_quat[3]).matrix()
        
        # 位置误差 (欧氏距离)
        pos_error = np.linalg.norm(meas_pos - pred_pos)
        
        # 姿态误差 (旋转向量范数)
        rot_error = np.linalg.norm(pin.log3(pred_rot.T @ meas_rot))
        
        errors.append([pos_error, rot_error])
    
    return np.array(errors)


def main():
    # 加载原始和标定后的模型
    robot_orig = pin.RobotWrapper.BuildFromURDF("robot.urdf", [pin.StdVec_StdString()])
    robot_calib = pin.RobotWrapper.BuildFromURDF("calibrated_robot.urdf", [pin.StdVec_StdString()])
    
    # 加载测量数据
    q, P, _ = load_measurements("measurements.csv")
    
    # 获取末端frame ID
    end_frame_id = robot_orig.model.getFrameId("tool0")
    
    # 计算误差
    errors_orig = compute_pose_error(robot_orig, q, P, end_frame_id)
    errors_calib = compute_pose_error(robot_calib, q, P, end_frame_id)
    
    # 统计
    print("=" * 60)
    print("标定前后误差对比")
    print("=" * 60)
    print(f"原始模型 - 位置误差: 均值={np.mean(errors_orig[:,0]):.4f}m, 标准差={np.std(errors_orig[:,0]):.4f}m")
    print(f"标定模型 - 位置误差: 均值={np.mean(errors_calib[:,0]):.4f}m, 标准差={np.std(errors_calib[:,0]):.4f}m")
    print(f"原始模型 - 姿态误差: 均值={np.mean(errors_orig[:,1]):.4f}rad, 标准差={np.std(errors_orig[:,1]):.4f}rad")
    print(f"标定模型 - 姿态误差: 均值={np.mean(errors_calib[:,1]):.4f}rad, 标准差={np.std(errors_calib[:,1]):.4f}rad")
    
    # 绘图
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    axes[0].hist(errors_orig[:,0], bins=30, alpha=0.5, label='原始模型', color='red')
    axes[0].hist(errors_calib[:,0], bins=30, alpha=0.5, label='标定模型', color='blue')
    axes[0].set_xlabel('位置误差 (m)')
    axes[0].set_ylabel('频数')
    axes[0].legend()
    axes[0].set_title('位置误差分布')
    
    axes[1].hist(errors_orig[:,1], bins=30, alpha=0.5, label='原始模型', color='red')
    axes[1].hist(errors_calib[:,1], bins=30, alpha=0.5, label='标定模型', color='blue')
    axes[1].set_xlabel('姿态误差 (rad)')
    axes[1].set_ylabel('频数')
    axes[1].legend()
    axes[1].set_title('姿态误差分布')
    
    plt.tight_layout()
    plt.savefig('calibration_validation.png', dpi=150)
    plt.show()
    print("\n✅ 验证完成! 图表已保存为 calibration_validation.png")


if __name__ == "__main__":
    main()