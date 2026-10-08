#!/usr/bin/env python3
"""
calibration.py
UR机器人运动学标定主脚本
"""

import numpy as np
import pinocchio as pin
from figaroh.calibration import BaseCalibration
import sys
from pathlib import Path


class URCobotCalibration(BaseCalibration):
    """
    UR机器人运动学标定类
    继承自 figaroh.calibration.BaseCalibration
    """
    
    def __init__(self, robot, config_file, **kwargs):
        """
        初始化标定器
        
        参数:
            robot: Pinocchio RobotWrapper 对象
            config_file: YAML配置文件路径
        """
        super().__init__(robot, config_file, **kwargs)
        # 获取末端执行器的frame ID
        self.end_frame_id = self.robot.model.getFrameId("tool0")
        if self.end_frame_id == self.robot.model.frames.size():
            print("警告: 未找到'tool0' frame，请检查URDF")
            # 尝试使用最后一个frame
            self.end_frame_id = self.robot.model.frames.size() - 1
            print(f"   使用最后一个frame: {self.robot.model.frames[-1].name}")
    
    def cost_function(self, var):
        """
        计算残差向量 (必须实现的核心方法)
        
        参数:
            var (np.ndarray): 当前的待优化参数向量
        
        返回:
            np.ndarray: 残差向量 (测量位姿 - 预测位姿)
        """
        # 1. 使用当前参数更新运动学模型
        self.update_model(var)
        
        # 2. 初始化残差列表
        residuals = []
        
        # 3. 遍历所有测量样本
        for i in range(self.NbSample):
            # 获取第 i 个样本的关节角度
            q = self.q_measured[i, :]
            
            # 使用更新后的模型进行正向运动学计算
            pin.framesForwardKinematics(self.robot.model, self.robot.data, q)
            oMf = self.robot.data.oMf[self.end_frame_id]
            
            # 获取预测的位姿
            pred_pos = oMf.translation
            pred_rot = oMf.rotation
            
            # 获取测量的位姿 (数据格式: [x, y, z, qw, qx, qy, qz])
            meas_pos = self.PEE_measured[i, 0:3]
            meas_quat = self.PEE_measured[i, 3:7]  # [qw, qx, qy, qz]
            
            # --- 计算残差 ---
            # 位置残差 (米)
            pos_res = meas_pos - pred_pos
            
            # 姿态残差: 使用对数映射 (旋转向量)
            meas_rot = pin.Quaternion(
                meas_quat[0], meas_quat[1], meas_quat[2], meas_quat[3]
            ).matrix()
            # 计算相对旋转 R_pred^T * R_meas，然后取对数
            rot_res = pin.log3(pred_rot.T @ meas_rot).flatten()  # 3x1 旋转向量
            
            # 组合残差 (6x1)
            sample_residual = np.hstack([pos_res, rot_res])
            residuals.append(sample_residual)
        
        # 将所有样本的残差堆叠成一个大的向量
        return np.hstack(residuals)


def main():
    print("=" * 60)
    print("UR机器人运动学标定")
    print("=" * 60)
    
    # 1. 配置文件路径
    config_file = "config.yaml"
    urdf_path = "robot.urdf"
    
    # 检查文件是否存在
    if not Path(config_file).exists():
        print(f"错误: 配置文件 '{config_file}' 不存在")
        sys.exit(1)
    if not Path(urdf_path).exists():
        print(f"错误: URDF文件 '{urdf_path}' 不存在")
        sys.exit(1)
    
    # 2. 加载机器人模型
    print(f"加载URDF: {urdf_path}")
    robot = pin.RobotWrapper.BuildFromURDF(
        urdf_path,
        [pin.StdVec_StdString()]  # package目录列表
    )
    print(f"  关节数: {robot.model.nq}")
    print(f"  有效关节: {[robot.model.names[i] for i in range(1, robot.model.nq+1)]}")
    
    # 3. 实例化标定类
    print(f"加载配置: {config_file}")
    calibrator = URCobotCalibration(
        robot=robot,
        config_file=config_file
    )
    
    # 4. 初始化标定流程
    # 这一步会加载数据，并使用QR分解识别可辨识的参数
    print("初始化标定流程...")
    calibrator.initialize()
    print(f"  加载了 {calibrator.NbSample} 个样本")
    print(f"  可辨识参数数量: {len(calibrator.var_)}")
    
    # 5. 执行标定优化
    print("\n开始标定优化...")
    calibrator.solve(
        method='lm',                # Levenberg-Marquardt
        max_iterations=3,           # 最大迭代轮数
        outlier_threshold=3.0,      # 离群值判定阈值
        plotting=True,              # 绘制优化过程
        save_results=True           # 保存结果
    )
    
    # 6. 输出结果
    print("\n" + "=" * 60)
    print("标定结果")
    print("=" * 60)
    print(f"标定状态: {calibrator.STATUS}")
    print(f"优化后的参数值:\n{calibrator.var_}")
    
    if hasattr(calibrator, 'evaluation_metrics'):
        print(f"评估指标: {calibrator.evaluation_metrics}")
    
    # 7. 导出标定后的URDF
    output_urdf = "calibrated_robot.urdf"
    print(f"\n导出标定后的URDF到: {output_urdf}")
    calibrator.update_urdf(output_urdf)
    print("✅ 标定完成!")


if __name__ == "__main__":
    main()