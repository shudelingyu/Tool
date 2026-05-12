import numpy as np

# ...existing code...
def hom_rot_y(theta):
    """返回绕 y 轴旋转 theta 的 4x4 齐次变换矩阵"""
    c = np.cos(theta)
    s = np.sin(theta)
    R = np.array([[ c, 0, s],
                  [ 0, 1, 0],
                  [-s, 0, c]])
    T = np.eye(4)
    T[:3,:3] = R
    return T

# ...existing code...
def hom_from_axis_angle(axis, angle=None):
    """由轴(axis)和角度(angle)构造 4x4 齐次变换（仅旋转）。
    支持两种调用：
      hom_from_axis_angle(axis, angle)     # axis 为方向向量，angle 为标量
      hom_from_axis_angle(axis_angle_vec)  # axis_angle_vec 为三维向量，模为角度
    """
    arr = np.asarray(axis, dtype=float)
    if angle is None:
        if arr.shape != (3,):
            raise ValueError("如果只传一个参数，必须是形状为 (3,) 的轴角向量")
        norm = np.linalg.norm(arr)
        if norm == 0:
            raise ValueError("轴角向量不可为零向量")
        u = arr / norm
        theta = norm
    else:
        norm = np.linalg.norm(arr)
        if norm == 0:
            raise ValueError("axis must be non-zero")
        u = arr / norm
        theta = float(angle)

    ux, uy, uz = u
    K = np.array([[ 0, -uz,  uy],
                  [ uz,  0, -ux],
                  [-uy, ux,   0]])
    I = np.eye(3)
    R = I + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)  # Rodrigues
    T = np.eye(4)
    T[:3,:3] = R
    return T

#主手数据kin
theta = 0.0  # 绕 y 轴旋转弧度，构造 T1
axis_angle_vec = [-1.4254 ,-0.1276, -1.0195]
#从手数据psmkin
# theta = 0.9667  # 绕 y 轴旋转弧度，构造 T1
# axis_angle_vec = [ -1.2455 ,-1.8084, 0.4435]

T1 = hom_rot_y(theta)
T2 = hom_from_axis_angle(axis_angle_vec)  # 直接传轴角向量

invT1 = np.linalg.inv(T1)  # 对纯旋转也可用 T1.T
result = invT1 @ T2

print("T1:\n", T1)
print("T2:\n", T2)
print("inv(T1) @ T2:\n", result)