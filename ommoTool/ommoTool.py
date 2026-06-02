#!/usr/bin/env python3
"""
计算 HDF5 文件中指定设备的位姿误差（起始点与终点的位置和姿态差异）

用法：
    python compute_pose_error.py data0.hdf5 Device_2607868765_3
输出示例：
    位置误差 (欧氏距离): 0.1234 米
    姿态误差 (旋转角度): 5.67 度
"""

import sys
import numpy as np
import h5py
from scipy.spatial.transform import Rotation

def quaternion_error(q1, q2):
    """
    计算两个四元数之间的姿态误差（最小旋转角度，单位：度）
    参数 q1, q2: 四元数 [x, y, z, w] 或 [w, x, y, z]？需明确
    这里假定输入为 [x, y, z, w]（即前三维为虚部，最后一维为实部）—— 需根据实际数据验证
    若实际存储为 [w, x, y, z]，可在读取后转换。
    """
    # 归一化
    q1 = q1 / np.linalg.norm(q1)
    q2 = q2 / np.linalg.norm(q2)
    # 四元数点积绝对值（用于计算夹角）
    dot = np.abs(np.dot(q1, q2))
    # 防止数值溢出
    dot = np.clip(dot, -1.0, 1.0)
    # 夹角（弧度） = 2 * arccos(dot)
    angle_rad = 2 * np.arccos(dot)
    # 转换为度数
    angle_deg = np.degrees(angle_rad)
    return angle_deg

def compute_pose_error(h5_path, device_group):
    """
    主函数：读取 Position 和 Quaternion，计算首尾位姿误差
    """
    with h5py.File(h5_path, 'r') as f:
        group_path = f"{device_group}"
        if group_path not in f:
            sys.exit(f"错误：组 '{group_path}' 不存在于文件中。")
        group = f[group_path]
        
        # 检查数据集
        if 'Position' not in group:
            sys.exit(f"错误：组 '{group_path}' 中没有 'Position' 数据集。")
        if 'Quaternion' not in group:
            sys.exit(f"错误：组 '{group_path}' 中没有 'Quaternion' 数据集。")
        
        pos_data = group['Position'][:]      # shape: (N, 1, 3) or (N,3)
        quat_data = group['Quaternion'][:]   # shape: (N, 1, 4) or (N,4)
        
        # 处理 shape：如果维度是3维且第二维为1，则压缩
        if pos_data.ndim == 3 and pos_data.shape[1] == 1:
            pos_data = pos_data[:, 0, :]   # 变为 (N, 3)
        if quat_data.ndim == 3 and quat_data.shape[1] == 1:
            quat_data = quat_data[:, 0, :]   # 变为 (N, 4)
        
        if pos_data.shape[0] < 2 or quat_data.shape[0] < 2:
            sys.exit("错误：数据样本数不足2，无法计算首尾误差。")
        
        # 取第一个和最后一个
        pos_first = pos_data[0, :]
        pos_last = pos_data[-1, :]
        quat_first = quat_data[0, :]
        quat_last = quat_data[-1, :]
        
        # 位置误差：欧氏距离
        pos_error = np.linalg.norm(pos_last - pos_first)
        
        # 姿态误差：四元数夹角
        # 注意：四元数存储顺序可能是 [w, x, y, z] 或 [x, y, z, w]
        # 这里假设存储为 [x, y, z, w] (最后的标量是 w)，请根据实际数据调整
        # 若实际为 [w, x, y, z]，取消下面注释转换：
        # quat_first = np.roll(quat_first, -1)  # 把w移到最后
        # quat_last = np.roll(quat_last, -1)
        
        angle_deg = quaternion_error(quat_first, quat_last)
        
        print(f"位置误差 (欧氏距离): {pos_error:.6f}  (单位与数据一致)")
        print(f"姿态误差 (旋转角度): {angle_deg:.4f} 度")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python compute_pose_error.py <HDF5文件> <设备组名>")
        print("示例: python compute_pose_error.py data0.hdf5 Device_2607868765_3")
        sys.exit(1)
    
    h5_file = sys.argv[1]
    device_group = sys.argv[2]
    compute_pose_error(h5_file, device_group)