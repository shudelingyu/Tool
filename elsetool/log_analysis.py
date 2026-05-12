import sys
import os
import time
from datetime import datetime
import subprocess

FINAL_EXT = '.xxx'

columns_patient = [
    ("tar_pos", 13), ("cur_pos", 13), ("tar_toq", 13), ("cur_toq", 13),
    ("status_word", 13), ("control_word", 13), ("error_code", 13),
    ("encoder1", 13), ("encoder2", 13), ("po", 6), ("ff_PDO", 5),
]
buttons_patient = ["rcmDragBtn", "flexDragBtn", "preMoveBtn1", "preMoveBtn2"]

columns_master = [
    ("cur_q", 8), ("cur_qabs", 8), ("tar_q", 8), 
    ("pdo6064", 8), ("pdo20a0", 8), 
    ("cur_toq", 8), ("tar_toq", 8), 
    ("cur_endpos", 12), 
    ("clipratio", 1), ("hall", 1), ("io_finger_clutch", 1), 
    ("control_word", 8), ("status_word", 8), ("error_code", 8), 
    ("view_angle", 1)
]
buttons_master = [] 

def get_header(columns, buttons):
    header = ["timestamp"] 
    for name, count in columns:
        for i in range(count):
            header.append(f"{name}/{i}") 
            
    header.extend(buttons)
    return header

def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

def parse_time_from_line(line):
    line = line.strip()
    if isinstance(line, bytes):
        try:
            line = line.decode('utf-8', errors='ignore')
        except:
            return None
            
    if not line or not line.startswith('['): return None
    end_bracket = line.find(']')
    if end_bracket == -1: return None
    
    time_str = line[1:end_bracket]
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
        return dt.timestamp()
    except ValueError:
        return None

def get_file_time_range(filepath):
    start_ts = None
    end_ts = None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for _ in range(10):
                line = f.readline()
                ts = parse_time_from_line(line)
                if ts is not None:
                    start_ts = ts
                    break
    except Exception:
        pass

    try:
        with open(filepath, 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            read_size = min(file_size, 8192) 
            f.seek(-read_size, 2)
            content = f.read().decode('utf-8', errors='ignore')
            lines = content.splitlines()
            for line in reversed(lines):
                ts = parse_time_from_line(line)
                if ts is not None:
                    end_ts = ts
                    break
    except Exception:
        pass

    return start_ts, end_ts

def format_ts(ts):
    if ts is None: return "??:??:??"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]

def detect_log_type(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for _ in range(20):
                line = f.readline()
                if "cur_q" in line and "pdo6064" in line:
                    return "MASTER"
    except:
        pass
    return "PATIENT"

def merge_and_convert(file_list):
    if not file_list: return

    print("\n>>> 正在扫描文件时间范围 (Head & Tail Check)...")
    print("-" * 78)
    print(f"{'File Name':<25} | {'Start Time':<12} -> {'End Time':<12} | {'Status'}")
    print("-" * 78)
    
    files_info = []
    for f in file_list:
        start, end = get_file_time_range(f)
        sort_key = start if start is not None else float('inf')
        files_info.append({
            'path': f, 'start': start, 'end': end, 'sort_key': sort_key
        })

    files_info.sort(key=lambda x: x['sort_key'])
    
    last_end_time = None
    
    for info in files_info:
        fname = os.path.basename(info['path'])
        s_str = format_ts(info['start'])
        e_str = format_ts(info['end'])
        
        status = "[OK]"
        if last_end_time is not None and info['start'] is not None:
            gap = info['start'] - last_end_time
            if gap < -0.1: 
                status = "[WARN] Overlap"
            elif gap > 5.0:
                status = f"[WARN] Gap {gap:.1f}s"
        
        print(f"{fname:<25} | {s_str} -> {e_str} | {status}")
        
        if info['end'] is not None:
            last_end_time = info['end']

    print("-" * 78)

    log_type = detect_log_type(files_info[0]['path'])
    print(f">>> 识别模式: {log_type}")

    if log_type == "MASTER":
        current_columns = columns_master
        current_buttons = buttons_master
    else:
        current_columns = columns_patient
        current_buttons = buttons_patient

    print(">>> 顺序确认无误，开始合并...\n")

    first_file = files_info[0]['path']
    dir_name = os.path.dirname(os.path.abspath(first_file))
    base_name = os.path.basename(first_file)
    output_filename = f"{base_name.split('.')[0]}_merged{FINAL_EXT}"
    final_path = os.path.join(dir_name, output_filename)

    header = get_header(current_columns, current_buttons)
    header_len = len(header)
    total_lines = 0
    dropped_lines = 0
    start_ts = time.time()

    try:
        with open(final_path, 'w', encoding='utf-8') as f_out:
            f_out.write(",".join(header) + "\n")

            for info in files_info:
                input_file = info['path']
                with open(input_file, 'r', encoding='utf-8') as f_in:
                    for line in f_in:
                        line = line.strip()
                        if not line or not line.startswith('['): continue
                        end_bracket = line.find(']')
                        if end_bracket == -1: continue
                        
                        time_str = line[1:end_bracket]
                        try:
                            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
                            timestamp_val = dt.timestamp()
                        except ValueError:
                            continue

                        data_part = line[end_bracket+1:]
                        
                        if log_type == "MASTER":
                            raw_items = data_part.split()
                            clean_data = [x for x in raw_items if is_number(x)]
                        else:
                            clean_data = [x.strip() for x in data_part.split(',') if x.strip()]
                        
                        expected_data_len = header_len - 1 
                        if len(clean_data) != expected_data_len:
                            dropped_lines += 1
                            if dropped_lines <= 5:
                                print(f"[WARN] 格式错误 (File: {os.path.basename(input_file)})")
                                print(f"       期望列数: {expected_data_len}, 实际列数: {len(clean_data)}")
                                print(f"       原始内容: {line[:60]}...") 
                            continue

                        csv_line = f"{timestamp_val:.3f}," + ",".join(clean_data) + "\n"
                        f_out.write(csv_line)
                        total_lines += 1
                        
                        if total_lines % 50000 == 0:
                            print(f"... Processed {total_lines} lines", end='\r')

    except Exception as e:
        print(f"\n[ERROR] : {e}")
        return

    duration = time.time() - start_ts
    print(f"\n\n[DONE] 合并完成! 生成: {output_filename}")
    print(f"       有效行数: {total_lines}")
    print(f"       耗时: {duration:.2f}s")
    
    if dropped_lines > 0:
        print("-" * 50)
        print(f"[WARNING] 共丢弃了 {dropped_lines} 行格式不匹配的数据！")
        print("请检查 columns_structure 定义是否与日志实际列数一致。")
        print("-" * 50)
    
    if os.name == 'nt':
        subprocess.run(['explorer', '/select,', final_path])

if __name__ == "__main__":
    files = sys.argv[1:]
    if len(files) > 0:
        merge_and_convert(files)
    else:
        print("[INFO] 请选中多个日志文件，拖拽到脚本上。")
        input("按回车键退出...")
