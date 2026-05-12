import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

def parse_log_file(filename):
    timestamps = []
    target_pos_j1 = []
    current_pos_j1 = []
    current_toq_j1 = []
    
    # 尝试自动检测编码
    encodings = ['utf-8', 'gbk', 'ascii']
    file = None
    
    for enc in encodings:
        try:
            file = open(filename, 'r', encoding=enc)
            break
        except UnicodeDecodeError:
            continue
            
    if not file:
        print("Error: Could not decode file. Please check the encoding.")
        return None, None, None, None

    with file:
        for line in file:
            line = line.strip()
            if not line:
                continue
                
            try:
                # 分割时间戳和数据部分
                # 格式: [2026-04-12 01:34:02.543] ,1.09...
                parts = line.split('] ,')
                if len(parts) != 2:
                    continue
                
                # 1. 解析时间戳
                timestamp_str = parts[0].strip('[')
                # 处理微秒/毫秒精度
                try:
                    timestamp = datetime.strptime(timestamp_str[:23], '%Y-%m-%d %H:%M:%S.%f')
                except ValueError:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                
                timestamps.append(timestamp)
                
                # 2. 解析数据部分
                data_parts = parts[1].split(',')
                
                # 确保数据长度足够 (根据你的格式定义，数据量很大，至少有 90+ 列)
                if len(data_parts) < 52: 
                    continue
                
                # --- 提取关节 1 (索引 0) 的数据 ---
                
                # 目标位置 (tar_pos): 第 1 组，第 1 个数 -> 索引 0
                t_pos = float(data_parts[0])
                
                # 当前位置 (cur_pos): 第 2 组，第 1 个数 -> 索引 13
                c_pos = float(data_parts[13])
                
                # 当前力矩 (cur_toq): 第 4 组，第 1 个数 -> 索引 39
                # 计算逻辑: tar_pos(13) + cur_pos(13) + tar_toq(13) = 39
                c_toq = float(data_parts[39])
                
                target_pos_j1.append(t_pos)
                current_pos_j1.append(c_pos)
                current_toq_j1.append(c_toq)
                
            except Exception as e:
                continue
    
    return timestamps, target_pos_j1, current_pos_j1, current_toq_j1

def plot_joint1_data(timestamps, target_pos, current_pos, current_toq):
    if not timestamps:
        print("No valid data to plot.")
        return
    
    # 转换时间格式
    time_numeric = mdates.date2num(timestamps)
    
    # 创建 2 行 1 列的子图
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
    fig.suptitle('Joint 1 Status Monitoring', fontsize=16, fontweight='bold')
    
    # --- 子图 1: 位置跟踪 ---
    ax1.plot(time_numeric, target_pos, 'b-', label='Target Position', linewidth=1.5)
    ax1.plot(time_numeric, current_pos, 'r-', label='Current Position', linewidth=1.5, alpha=0.7)
    
    ax1.set_ylabel('Position (rad)', fontsize=12)
    ax1.set_title('Joint 1 Position Tracking', fontsize=14)
    ax1.legend(loc='upper right')
    ax1.grid(True, linestyle='--', alpha=0.5)
    
    # --- 子图 2: 力矩反馈 ---
    # 注意：这里只画了当前力矩，因为日志格式中 tar_toq 是第3组数据
    # 如果你也需要目标力矩，可以添加 data_parts[26]
    ax2.plot(time_numeric, current_toq, 'g-', label='Current Torque', linewidth=1.5)
    
    ax2.set_ylabel('Torque (N·m)', fontsize=12)
    ax2.set_xlabel('Time', fontsize=12)
    ax2.set_title('Joint 1 Torque Feedback', fontsize=14)
    ax2.legend(loc='upper right')
    ax2.grid(True, linestyle='--', alpha=0.5)
    
    # 设置 X 轴时间格式
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    
    plt.tight_layout()
    plt.show()

def main():
    # 请确保文件名正确
    filename = './mms'
    
    print(f"Parsing file: {filename}...")
    timestamps, t_pos, c_pos, c_toq = parse_log_file(filename)
    
    if timestamps:
        print(f"Successfully parsed {len(timestamps)} records.")
        print("Plotting Joint 1 graphs...")
        plot_joint1_data(timestamps, t_pos, c_pos, c_toq)
        print("Done.")
    else:
        print("No data found. Please check the file format and path.")

if __name__ == "__main__":
    main()