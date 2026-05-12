import matplotlib.pyplot as plt
import re
from datetime import datetime
import numpy as np

def parse_log_file(file_path):
    """
    解析日志文件，提取时间戳和八个关节的cur_q、tar_q数据
    对于相同的时间戳只取第一组数据
    """
    timestamps = []
    cur_q_data = []  # 存储八个关节的cur_q数据
    tar_q_data = []  # 存储八个关节的tar_q数据
    
    # 用于记录已经处理过的时间戳
    processed_timestamps = set()
    
    # 正则表达式匹配时间戳和cur_q/tar_q数据
    timestamp_pattern = r'\[(.*?)\]'
    # 匹配cur_q后面的8个浮点数
    cur_q_pattern = r'cur_q ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+)'
    # 匹配tar_q后面的8个浮点数
    tar_q_pattern = r'tar_q ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+) ([-0-9.]+)'
    
    with open(file_path, 'r') as file:
        for line_num, line in enumerate(file, 1):
            # 匹配时间戳
            timestamp_match = re.search(timestamp_pattern, line)
            if not timestamp_match:
                continue
                
            timestamp_str = timestamp_match.group(1)
            
            # 检查是否已经处理过这个时间戳
            if timestamp_str in processed_timestamps:
                continue
                
            # 匹配cur_q数据
            cur_q_match = re.search(cur_q_pattern, line)
            # 匹配tar_q数据
            tar_q_match = re.search(tar_q_pattern, line)
            
            if cur_q_match and tar_q_match:
                # 解析时间戳
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                    
                    # 解析cur_q的8个关节数据
                    cur_q_values = []
                    for i in range(1, 9):  # 有8个捕获组
                        cur_q_values.append(float(cur_q_match.group(i)))
                    
                    # 解析tar_q的8个关节数据
                    tar_q_values = []
                    for i in range(1, 9):  # 有8个捕获组
                        tar_q_values.append(float(tar_q_match.group(i)))
                    
                    # 添加到结果列表
                    timestamps.append(timestamp)
                    cur_q_data.append(cur_q_values)
                    tar_q_data.append(tar_q_values)
                    
                    # 标记这个时间戳已经处理过
                    processed_timestamps.add(timestamp_str)
                    
                except ValueError as e:
                    print(f"解析错误在行 {line_num}: {line.strip()}, 错误: {e}")
                    continue
    
    return timestamps, cur_q_data, tar_q_data

def plot_joint_data(timestamps, cur_q_data, tar_q_data, output_file=None):
    """
    绘制八个关节的cur_q和tar_q数据
    """
    # 将数据转换为numpy数组便于处理
    cur_q_array = np.array(cur_q_data)
    tar_q_array = np.array(tar_q_data)
    
    # 计算时间偏移（以秒为单位，从第一个时间点开始）
    time_offset = [(t - timestamps[0]).total_seconds() for t in timestamps]
    
    # 创建8个子图，每个关节一个
    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    fig.suptitle('Joint Angles: cur_q vs tar_q', fontsize=16, fontweight='bold')
    
    # 为每个关节绘制图表
    for joint in range(8):
        row = joint // 4
        col = joint % 4
        
        ax = axes[row, col]
        
        # 绘制当前值和目标值
        ax.plot(time_offset, cur_q_array[:, joint], 'b-', label='cur_q', linewidth=1.5, alpha=0.8)
        ax.plot(time_offset, tar_q_array[:, joint], 'r--', label='tar_q', linewidth=1.5, alpha=0.8)
        
        ax.set_title(f'Joint {joint+1}')
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Angle (rad)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # 添加数值统计信息
        cur_mean = np.mean(cur_q_array[:, joint])
        tar_mean = np.mean(tar_q_array[:, joint])
        ax.text(0.02, 0.98, f'cur mean: {cur_mean:.3f}\ntar mean: {tar_mean:.3f}', 
                transform=ax.transAxes, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    # 保存图表
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"图表已保存为: {output_file}")
    
    plt.show()
    
    # # 打印基本统计信息
    # print("\n数据统计信息:")
    # print("=" * 50)
    # for joint in range(8):
    #     cur_mean = np.mean(cur_q_array[:, joint])
    #     tar_mean = np.mean(tar_q_array[:, joint])
    #     cur_std = np.std(cur_q_array[:, joint])
    #     tar_std = np.std(tar_q_array[:, joint])
        
    #     print(f"关节 {joint+1}:")
    #     print(f"  cur_q - 均值: {cur_mean:.4f}, 标准差: {cur_std:.4f}")
    #     print(f"  tar_q - 均值: {tar_mean:.4f}, 标准差: {tar_std:.4f}")
    #     print()

def main():
    # 配置参数
    log_file_path = './RightDataModel.txt'  # 修改为您的日志文件路径
    output_image = 'joint_angles_plot.png'  # 输出图片文件名
    
    try:
        # 解析日志文件
        print("正在解析日志文件...")
        timestamps, cur_q_data, tar_q_data = parse_log_file(log_file_path)
        
        if not timestamps:
            print("未找到有效数据，请检查文件路径和格式")
            return
        
        print(f"成功解析 {len(timestamps)} 个数据点")
        print(f"时间范围: {timestamps[0]} 到 {timestamps[-1]}")
        print(f"持续时间: {(timestamps[-1] - timestamps[0]).total_seconds():.3f} 秒")
        
        # 绘制图表
        print("正在生成图表...")
        plot_joint_data(timestamps, cur_q_data, tar_q_data, output_image)
        
    except FileNotFoundError:
        print(f"错误: 找不到文件 {log_file_path}")
    except Exception as e:
        print(f"发生错误: {e}")

if __name__ == "__main__":
    main()