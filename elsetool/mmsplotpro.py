import matplotlib.pyplot as plt
import re
from datetime import datetime
import numpy as np
import argparse
from typing import List, Dict, Tuple, Optional

TIME_FORMATS = ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']

def try_parse_time(s: str) -> Optional[datetime]:
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def parse_joints_arg(s: str, max_joints: int = 32) -> List[int]:
    """解析关节参数，如 "1-8,10,12" -> [0-based indices]"""
    parts = s.split(',')
    res = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if '-' in p:
            a, b = p.split('-', 1)
            ia, ib = int(a), int(b)
            res.extend(list(range(ia - 1, ib)))
        else:
            res.append(int(p) - 1)
    # 限制范围
    res = [i for i in res if 0 <= i < max_joints]
    return sorted(set(res))

def parse_log_file(file_path: str, keys: List[str]) -> Tuple[List[datetime], Dict[str, List[List[float]]]]:
    """
    解析日志文件，按 keys 提取每行对应的数值（每个 key 对应多个关节值）
    返回 timestamps 列表和数据字典 data[key] -> list of [vals]
    """
    timestamps: List[datetime] = []
    data: Dict[str, List[List[float]]] = {k: [] for k in keys}

    timestamp_pattern = r'\[(.*?)\]'
    # 为每个 key 生成正则
    key_patterns = {k: re.compile(re.escape(k) + r'\s+([-0-9. ]+)') for k in keys}

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            ts_m = re.search(timestamp_pattern, line)
            if not ts_m:
                continue
            ts_str = ts_m.group(1)
            ts = try_parse_time(ts_str)
            if not ts:
                continue

            values_for_line = {}
            all_found = True
            for k, pat in key_patterns.items():
                m = pat.search(line)
                if not m:
                    all_found = False
                    break
                try:
                    vals = [float(x) for x in m.group(1).split()]
                except ValueError:
                    all_found = False
                    break
                values_for_line[k] = vals

            if not all_found:
                continue

            # 通过到这里说明这行所有 keys 都有值
            timestamps.append(ts)
            for k in keys:
                data[k].append(values_for_line[k])

    return timestamps, data

def filter_time_range(timestamps: List[datetime], data: Dict[str, List[List[float]]],
                      start: Optional[datetime], end: Optional[datetime]) -> Tuple[List[datetime], Dict[str, List[List[float]]]]:
    if start is None and end is None:
        return timestamps, data
    new_ts = []
    new_data = {k: [] for k in data.keys()}
    for idx, t in enumerate(timestamps):
        if start and t < start:
            continue
        if end and t > end:
            continue
        new_ts.append(t)
        for k in data.keys():
            new_data[k].append(data[k][idx])
    return new_ts, new_data

def plot_joint_data(timestamps: List[datetime],
                    data: Dict[str, List[List[float]]],
                    keys: List[str],
                    joints: List[int],
                    output_file: Optional[str] = None,
                    dpi: int = 200,
                    show_plot: bool = True):
    if not timestamps:
        print("没有数据可绘制")
        return

    # 时间偏移（秒）
    t0 = timestamps[0]
    time_offset = [(t - t0).total_seconds() for t in timestamps]

    n_joints = max((len(data[key][0]) for key in keys), default=0)
    if not joints:
        joints = list(range(n_joints))
    # 限制关节索引在实际范围内
    joints = [j for j in joints if 0 <= j < n_joints]
    if not joints:
        print("未找到有效的关节索引可绘制")
        return

    # 转为 numpy
    np_data = {k: np.array(data[k]) for k in keys}  # shape (N, joint_count)

    # 创建子图（2行4列，最多8个子图；超出按多页处理）
    per_page = 8
    pages = (len(joints) + per_page - 1) // per_page
    styles = ['b-', 'r--', 'g-', 'c--', 'm-', 'y--', 'k-', 'b--']
    marker_colors = ['blue', 'red', 'green', 'cyan', 'magenta', 'orange', 'black', 'brown']

    for page in range(pages):
        page_joints = joints[page * per_page:(page + 1) * per_page]
        rows = 2
        cols = 4
        fig, axes = plt.subplots(rows, cols, figsize=(20, 10))
        fig.suptitle('tips: ' + ','.join(keys), fontsize=16, fontweight='bold')

        for idx, joint in enumerate(page_joints):
            row = idx // cols
            col = idx % cols
            ax = axes[row, col]
            for i, key in enumerate(keys):
                arr = np_data[key]
                if arr.ndim == 2 and joint < arr.shape[1]:
                    ax.plot(time_offset, arr[:, joint], styles[i % len(styles)], label=key, linewidth=1.5, alpha=0.85)

                    # 标注最大值和最小值
                    try:
                        col_arr = arr[:, joint]
                        if col_arr.size > 0:
                            imax = int(np.nanargmax(col_arr))
                            imin = int(np.nanargmin(col_arr))
                            x_max = time_offset[imax]
                            y_max = float(col_arr[imax])
                            x_min = time_offset[imin]
                            y_min = float(col_arr[imin])

                            color = marker_colors[i % len(marker_colors)]
                            ax.plot(x_max, y_max, marker='o', color=color, markersize=6)
                            ax.plot(x_min, y_min, marker='s', color=color, markersize=6)

                            # 文本稍做偏移，避免重叠
                            y_offset = (np.max(col_arr) - np.min(col_arr)) * 0.05 if (np.max(col_arr) - np.min(col_arr)) != 0 else 0.01
                            ax.annotate(f"max {key}\n{y_max:.3f}", xy=(x_max, y_max),
                                        xytext=(5, 5 + i*10), textcoords='offset points',
                                        color=color, fontsize=8,
                                        bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.6))
                            ax.annotate(f"min {key}\n{y_min:.3f}", xy=(x_min, y_min),
                                        xytext=(5, -15 - i*10), textcoords='offset points',
                                        color=color, fontsize=8,
                                        bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.6))
                    except Exception:
                        # 忽略单条或异常数据导致的标注错误
                        pass

            ax.set_title(f'joint {joint+1}')
            ax.set_xlabel('time (s)')
            ax.set_ylabel('value')
            ax.legend()
            ax.grid(True, alpha=0.3)

        # 隐藏多余子图
        total_slots = rows * cols
        for extra in range(len(page_joints), total_slots):
            r = extra // cols
            c = extra % cols
            axes[r, c].axis('off')

        plt.tight_layout()
        if output_file:
            # 分页命名
            if pages == 1:
                out = output_file
            else:
                base, ext = (output_file.rsplit('.', 1) + ['png'])[:2]
                out = f"{base}_page{page+1}.{ext}"
            plt.savefig(out, dpi=dpi, bbox_inches='tight')
            print(f"已保存: {out}")

        if show_plot:
            plt.show()
        else:
            plt.close(fig)

def parse_args():
    p = argparse.ArgumentParser(description="从日志绘制关节/字段数据 (示例字段格式: 'cur_q 0.1 0.2 ...')")
    p.add_argument('-f', '--file',default='F:/coord_test/Left', help='日志文件路径')
    p.add_argument('-k', '--keys', default='cur_q', help='要提取并绘制的字段，逗号分隔，默认 cur_q,tar_q')
    p.add_argument('-j', '--joints', default='1-7', help='要绘制的关节索引，如 1-8 或 1,3,5 (1-based)')
    p.add_argument('--start', default=None, help="起始时间 (完整格式 'YYYY-mm-dd HH:MM:SS[.fff]') 或秒偏移（相对于日志第一个时间点）")
    p.add_argument('--end', default=None, help="结束时间，同 start")
    p.add_argument('-o', '--output', default=None, help='输出图片文件名（可选）')
    p.add_argument('--dpi', type=int, default=200, help='保存图片 DPI')
    p.add_argument('--no-show', dest='show', action='store_false', help='不弹出图形窗口（仅保存）')
    return p.parse_args()

def main():
    args = parse_args()
    keys = [k.strip() for k in args.keys.split(',') if k.strip()]
    joints = parse_joints_arg(args.joints, max_joints=64)

    try:
        print("正在解析日志文件...")
        timestamps, data = parse_log_file(args.file, keys)
        if not timestamps:
            print("未找到有效数据，请检查文件路径/字段/格式")
            return

        # 解析 start/end
        start = None
        end = None
        if args.start:
            t = try_parse_time(args.start)
            if t:
                start = t
            else:
                try:
                    sec = float(args.start)
                    start = timestamps[0] + np.timedelta64(int(sec * 1e3), 'ms').astype('datetime64[ms]').astype(datetime)
                except Exception:
                    start = None
        if args.end:
            t = try_parse_time(args.end)
            if t:
                end = t
            else:
                try:
                    sec = float(args.end)
                    end = timestamps[0] + np.timedelta64(int(sec * 1e3), 'ms').astype('datetime64[ms]').astype(datetime)
                except Exception:
                    end = None

        timestamps, data = filter_time_range(timestamps, data, start, end)

        print(f"解析到 {len(timestamps)} 条记录，字段: {', '.join(keys)}")
        plot_joint_data(timestamps, data, keys, joints, output_file=args.output, dpi=args.dpi, show_plot=args.show)

    except FileNotFoundError:
        print(f"错误: 找不到文件 {args.file}")
    except Exception as e:
        print(f"发生错误: {e}")
        raise

if __name__ == "__main__":
    main()