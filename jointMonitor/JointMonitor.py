#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import paramiko
import re
import os
import sys
import threading
import math
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field


# ==================== 数据结构 ====================
@dataclass
class SlaveData:
    arm_id: int
    cur_pos: list = field(default_factory=lambda: [0.0] * 12)
    timestamp: str = ""


@dataclass
class MasterData:
    arm_name: str
    cur_q: list = field(default_factory=lambda: [0.0] * 8)
    timestamp: str = ""
    view_angle: Optional[float] = None


# ==================== SSH读取器 ====================
class SSHReader:
    def __init__(self, log_callback=None):
        self.master_client: Optional[paramiko.SSHClient] = None
        self.slave_client: Optional[paramiko.SSHClient] = None
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def connect_master(self, ip: str, username: str, password: str, port: int = 22) -> bool:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=ip, port=port, username=username, password=password, timeout=5)
            self.master_client = client
            return True
        except Exception as e:
            print(f"主手连接失败: {e}")
            return False

    def connect_slave(self, ip: str, username: str, password: str, port: int = 22) -> bool:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=ip, port=port, username=username, password=password, timeout=5)
            self.slave_client = client
            return True
        except Exception as e:
            print(f"从手连接失败: {e}")
            return False

    def get_last_line(self, client: paramiko.SSHClient, log_path: str) -> Optional[str]:
        try:
            stdin, stdout, stderr = client.exec_command(f'test -f "{log_path}" && echo "exists" || echo "not_exists"')
            check_result = stdout.read().decode('utf-8', errors='ignore').strip()
            if check_result != "exists":
                self._log(f"错误：日志文件不存在 - {log_path}")
                return None

            stdin, stdout, stderr = client.exec_command(f'tail -n 1 "{log_path}" 2>&1')
            line = stdout.read().decode('utf-8', errors='ignore').strip()
            error_msg = stderr.read().decode('utf-8', errors='ignore').strip()
            if error_msg:
                self._log(f"读取文件失败 {log_path}: {error_msg}")
                return None

            if not line or len(line) < 10:
                stdin2, stdout2, stderr2 = client.exec_command(f'tail -n 2 "{log_path}" 2>&1 | head -n 1')
                line2 = stdout2.read().decode('utf-8', errors='ignore').strip()
                error_msg2 = stderr2.read().decode('utf-8', errors='ignore').strip()
                if error_msg2:
                    self._log(f"读取文件失败 {log_path}: {error_msg2}")
                    return None
                if line2 and len(line2) >= 10:
                    return line2
                else:
                    self._log(f"警告：日志文件内容过短或为空 - {log_path}")
                    return None
            return line
        except Exception as e:
            self._log(f"读取文件异常 {log_path}: {type(e).__name__}: {e}")
            return None

    def parse_slave_log(self, log_line: str, arm_id: int) -> SlaveData:
        data = SlaveData(arm_id)
        if not log_line:
            return data

        parts = [p.strip() for p in log_line.split(',') if p.strip() != '']
        if not parts:
            return data

        try:
            motion_cmd = int(parts[-1])
        except ValueError:
            motion_cmd = -1

        if len(parts) < 100:
            if len(parts) >= 16:
                try:
                    cur_pos_simple = parts[9:16]
                    for i, val in enumerate(cur_pos_simple):
                        data.cur_pos[5 + i] = float(val)
                    self._log(f"从臂{arm_id} (motion_cmd={motion_cmd}) 使用简化格式 (关节5-12)")
                except ValueError as e:
                    self._log(f"解析从臂{arm_id}简化格式失败: {e}")
            else:
                self._log(f"从臂{arm_id} 简化格式数据不足，实际字段数 {len(parts)}")
        else:
            if len(parts) >= 26:
                try:
                    cur_pos_strs = parts[14:26]
                    data.cur_pos = [float(v) for v in cur_pos_strs]
                    self._log(f"从臂{arm_id} (motion_cmd={motion_cmd}) 使用完整格式 (13个关节)")
                except ValueError as e:
                    self._log(f"解析从臂{arm_id}完整格式失败: {e}")
            else:
                self._log(f"从臂{arm_id} 完整格式数据不足，实际字段数 {len(parts)}")

        data.timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        return data

    def parse_master_log(self, log_line: str, arm_name: str) -> MasterData:
        data = MasterData(arm_name)
        if not log_line:
            return data

        pattern_q = r'cur_q\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)'
        pattern_qabs = r'cur_qabs\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)'

        match_q = re.search(pattern_q, log_line)
        match_qabs = re.search(pattern_qabs, log_line)

        q_vals = [0.0] * 8
        qabs_vals = [0.0] * 8

        if match_q:
            q_vals = [float(g) for g in match_q.groups()]
        if match_qabs:
            qabs_vals = [float(g) for g in match_qabs.groups()]

        result = [0.0] * 7
        for i in range(6):
            result[i] = qabs_vals[i]

        j7 = q_vals[6]
        # 将 J7 归一化到 [-π, π] 范围（弧度）
        # 使用 math.remainder 或手动取模，更优雅地处理角度范围
        j7 = math.remainder(j7, 2 * math.pi)
        result[6] = j7

        data.cur_q = result
            
        
        data.cur_q = result

        view_pattern = r'view_angle\s+([\d.-]+)'
        match_view = re.search(view_pattern, log_line)
        if match_view:
            data.view_angle = float(match_view.group(1))

        data.timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        return data

    def read_slave(self, arm_id: int) -> Optional[SlaveData]:
        if not self.slave_client:
            return None
        log_path = f"/data/log/rt/mmsArm{arm_id}/mmsArm{arm_id}"
        line = self.get_last_line(self.slave_client, log_path)
        if line:
            return self.parse_slave_log(line, arm_id)
        return None

    def read_master(self, arm_name: str) -> Optional[MasterData]:
        if not self.master_client:
            return None
        log_path = f"/data/log/rt/{arm_name}DataModel/{arm_name}DataModel"
        line = self.get_last_line(self.master_client, log_path)
        if line:
            return self.parse_master_log(line, arm_name)
        return None

    def disconnect_all(self):
        if self.master_client:
            self.master_client.close()
            self.master_client = None
        if self.slave_client:
            self.slave_client.close()
            self.slave_client = None


# ==================== 主界面 ====================
class SimpleMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("机械臂关节角监控系统")
        self.root.geometry("1150x920")
        self.center_window()
        self.root.resizable(True, True)

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TLabel', font=('微软雅黑', 9))
        self.style.configure('TButton', font=('微软雅黑', 9), padding=3)
        self.style.configure('TLabelframe.Label', font=('微软雅黑', 9, 'bold'))
        self.style.configure('Accent.TButton', foreground='white', background='#0078D7')
        self.style.map('Accent.TButton', background=[('active', '#005A9E')])

        self.ssh = SSHReader(log_callback=self.log)
        self.master_connected = False
        self.slave_connected = False
        self.arm_widgets = {}
        self.batch_refresh_count = 0
        self.batch_refresh_total = 0
        self.file_locks = {}

        self.setup_ui()
        self.set_defaults()

    def center_window(self):
        self.root.update_idletasks()
        w = 1200
        h = 720
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    def set_defaults(self):
        self.slave_ip.delete(0, tk.END)
        self.slave_ip.insert(0, "192.168.11.11")
        self.master_ip.delete(0, tk.END)
        self.master_ip.insert(0, "192.168.11.13")
        self.slave_user.delete(0, tk.END)
        self.slave_user.insert(0, "codeit")
        self.slave_pwd.delete(0, tk.END)
        self.slave_pwd.insert(0, "1")
        self.master_user.delete(0, tk.END)
        self.master_user.insert(0, "codeit")
        self.master_pwd.delete(0, tk.END)
        self.master_pwd.insert(0, "1")

    def setup_ui(self):
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)

        # 连接区域
        conn_frame = ttk.LabelFrame(main, text="连接配置", padding="8")
        conn_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(conn_frame, text="从手电脑").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="IP:").grid(row=1, column=0, padx=5, sticky=tk.E)
        self.slave_ip = ttk.Entry(conn_frame, width=16)
        self.slave_ip.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="用户名:").grid(row=2, column=0, padx=5, sticky=tk.E)
        self.slave_user = ttk.Entry(conn_frame, width=16)
        self.slave_user.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="密码:").grid(row=3, column=0, padx=5, sticky=tk.E)
        self.slave_pwd = ttk.Entry(conn_frame, width=16, show="*")
        self.slave_pwd.grid(row=3, column=1, padx=5, pady=2, sticky=tk.W)

        ttk.Label(conn_frame, text="主手电脑").grid(row=0, column=2, padx=20, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="IP:").grid(row=1, column=2, padx=20, sticky=tk.E)
        self.master_ip = ttk.Entry(conn_frame, width=16)
        self.master_ip.grid(row=1, column=3, padx=5, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="用户名:").grid(row=2, column=2, padx=20, sticky=tk.E)
        self.master_user = ttk.Entry(conn_frame, width=16)
        self.master_user.grid(row=2, column=3, padx=5, pady=2, sticky=tk.W)
        ttk.Label(conn_frame, text="密码:").grid(row=3, column=2, padx=20, sticky=tk.E)
        self.master_pwd = ttk.Entry(conn_frame, width=16, show="*")
        self.master_pwd.grid(row=3, column=3, padx=5, pady=2, sticky=tk.W)

        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=0, column=4, rowspan=4, padx=20, sticky=tk.N)
        self.connect_btn = ttk.Button(btn_frame, text="连接", command=self.do_connect, width=12, style='Accent.TButton')
        self.connect_btn.pack(pady=5)
        self.refresh_all_btn = ttk.Button(btn_frame, text="全部刷新", command=self.refresh_all, width=12, state=tk.DISABLED)
        self.refresh_all_btn.pack(pady=5)
        self.status_label = ttk.Label(btn_frame, text="未连接", foreground="red")
        self.status_label.pack(pady=5)

        # 机械臂数据列表
        list_frame = ttk.LabelFrame(main, text="关节角实时数据", padding="8")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        arms = [
            (1, "从臂1", "slave", 0),
            (2, "从臂2", "slave", 1),
            (3, "从臂3", "slave", 2),
            (4, "从臂4", "slave", 3),
            (5, "主手 LEFT", "master", "Left"),
            (6, "主手 RIGHT", "master", "Right")
        ]
        for idx, (_, display_name, arm_type, identifier) in enumerate(arms):
            self._add_arm_row(scrollable_frame, display_name, arm_type, identifier, idx % 2 == 0)

        # 日志区域
        log_frame = ttk.LabelFrame(main, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=False, side=tk.BOTTOM)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, font=("Consolas", 9),
                                                  bg="#1E1E1E", fg="#D4D4D4", insertbackground="white")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _add_arm_row(self, parent, display_name, arm_type, identifier, even):
        row = tk.Frame(parent, bg='#F0F0F0' if even else '#FFFFFF', height=40)
        row.pack(fill=tk.X, pady=2, padx=5)

        lbl_name = tk.Label(row, text=f"{display_name}:", font=("微软雅黑", 10, "bold"),
                            width=12, anchor=tk.W, bg=row['bg'])
        lbl_name.pack(side=tk.LEFT, padx=(10, 15))

        lbl_data = tk.Label(row, text="未连接", fg="gray", font=("Consolas", 9),
                            anchor=tk.W, cursor="hand2", bg=row['bg'])
        lbl_data.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        lbl_data.bind("<Button-1>", lambda e, disp=display_name: self.copy_arm_data(disp, lbl_data))

        btn_frame = tk.Frame(row, bg=row['bg'])
        btn_frame.pack(side=tk.RIGHT, padx=10)

        refresh_btn = ttk.Button(btn_frame, text="刷新",
                                 command=lambda: self.refresh_arm(arm_type, identifier, is_batch=False),
                                 width=6, state=tk.DISABLED)
        refresh_btn.pack(side=tk.LEFT, padx=2)

        save_btn = ttk.Button(btn_frame, text="保存",
                              command=lambda: self.save_arm_current_data(arm_type, identifier, display_name),
                              width=6, state=tk.DISABLED)
        save_btn.pack(side=tk.LEFT, padx=2)

        delete_btn = ttk.Button(btn_frame, text="删除最新",
                                command=lambda: self.confirm_delete(arm_type, identifier, display_name),
                                width=8, state=tk.DISABLED)
        delete_btn.pack(side=tk.LEFT, padx=2)

        key = (arm_type, identifier)
        self.arm_widgets[key] = (lbl_data, refresh_btn, save_btn, delete_btn)

    def copy_arm_data(self, display_name, lbl_data):
        text = lbl_data.cget("text")
        if text and text not in ("未连接", "读取失败"):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            copy_content = f"{display_name} [{timestamp}]: {text}"
            self.root.clipboard_clear()
            self.root.clipboard_append(copy_content)
            self.root.update()
            self.log(f"已复制 {display_name} 数据 ({len(text)} 字符)")
        else:
            self.log(f"无法复制 {display_name} 数据：当前无有效数据")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        print(f"[{ts}] {msg}")

    # ---------- 文件操作辅助 ----------
    def _get_data_dir(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def _get_file_line_count(self, filepath: str) -> int:
        """返回文件的数据行数（不包括表头），若文件不存在或只有表头则返回0"""
        if not os.path.exists(filepath):
            return 0
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # 第一行是表头，剩下是数据行
            return max(0, len(lines) - 1)
        except Exception:
            return 0

    def _write_joint_file(self, filepath: str, angle_vals: List[float], num_joints: int, prefix: str) -> int:
        """写入数据，返回写入的行号（从1开始）"""
        if filepath not in self.file_locks:
            self.file_locks[filepath] = threading.Lock()

        with self.file_locks[filepath]:
            try:
                file_exists = os.path.exists(filepath)
                need_header = not file_exists or os.path.getsize(filepath) == 0

                # 计算当前数据行数（即新行号）
                current_lines = 0
                if file_exists and not need_header:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        current_lines = len(f.readlines()) - 1  # 减去表头
                new_line_no = current_lines + 1

                with open(filepath, 'a', encoding='utf-8') as f:
                    if need_header:
                        header_cols = ["name"] + [f"J{i+1}" for i in range(num_joints)]
                        header_line = " ".join(header_cols)
                        f.write(header_line + "\n")
                        self.log(f"创建文件并写入表头: {os.path.basename(filepath)}")
                        new_line_no = 1  # 第一行数据

                    values_str = " ".join([f"{v:.6f}" for v in angle_vals])
                    data_line = f"{prefix}: {values_str}"
                    f.write(data_line + "\n")

                self.log(f"数据已追加到 {os.path.basename(filepath)} (第{new_line_no}个点)")
                return new_line_no
            except Exception as e:
                self.log(f"写入文件失败 {filepath}: {e}")
                return -1

    def save_arm_current_data(self, arm_type: str, identifier, display_name):
        """保存当前显示的关节角数据到文件"""
        key = (arm_type, identifier)
        lbl_data, _, _, _ = self.arm_widgets[key]
        text = lbl_data.cget("text")
        if text in ("未连接", "读取失败"):
            self.log(f"无法保存 {display_name}：当前无有效数据")
            messagebox.showwarning("警告", f"{display_name} 当前无有效数据，请先刷新")
            return

        # 解析角度值
        try:
            angles = [float(x.strip()) for x in text.split(',')]
        except ValueError as e:
            self.log(f"解析 {display_name} 数据失败: {e}")
            messagebox.showerror("错误", f"{display_name} 数据格式错误，无法保存")
            return

        # 保存
        if arm_type == "master":
            if len(angles) != 7:
                self.log(f"警告：主手{identifier}关节数异常({len(angles)}), 期望7")
            data_dir = self._get_data_dir()
            if identifier == "Left":
                filename = "mtm1_joint.cst"
            elif identifier == "Right":
                filename = "mtm2_joint.cst"
            else:
                return
            filepath = os.path.join(data_dir, filename)
            line_no = self._write_joint_file(filepath, angles, 7, "addlpos")
            if line_no > 0:
                self.log(f"{display_name} 关节数据保存完成，第{line_no}个点")
            # 注意：view_angle 不在这里保存，view_angle 是在刷新时自动保存的（从SSH日志中读取）
            # 若用户希望单独保存 view_angle 也能保存，可额外处理，但根据需求，view_angle 跟随刷新保存。
            # 为保持简洁，此处只保存关节数据。view_angle 的保存逻辑保留在刷新时自动执行。

        elif arm_type == "slave":
            if len(angles) != 12:
                self.log(f"警告：从臂{identifier}关节数异常({len(angles)}), 期望12")
            data_dir = self._get_data_dir()
            front_8 = angles[:8]
            back_4 = angles[8:12]
            psm_file = os.path.join(data_dir, f"psm{identifier+1}_joint.cst")
            inst_file = os.path.join(data_dir, f"inst{identifier+1}_joint.cst")
            line_no_psm = self._write_joint_file(psm_file, front_8, 8, "actpos")
            line_no_inst = self._write_joint_file(inst_file, back_4, 4, "actpos")
            if line_no_psm > 0:
                self.log(f"{display_name} 前8关节保存完成，第{line_no_psm}个点")
            if line_no_inst > 0:
                self.log(f"{display_name} 后4关节保存完成，第{line_no_inst}个点")

    def save_view_angle_to_file(self, view_angle: float):
        if view_angle is None:
            return
        data_dir = self._get_data_dir()
        filepath = os.path.join(data_dir, "view_angle.cst")
        self._write_joint_file(filepath, [view_angle], 1, "view_angle")

    # ---------- 删除功能（带行号提示） ----------
    def delete_last_line_with_prompt(self, filepath: str, description: str) -> bool:
        """删除文件最后一行，并提示删除的行号，返回是否成功"""
        if filepath not in self.file_locks:
            self.file_locks[filepath] = threading.Lock()

        with self.file_locks[filepath]:
            try:
                if not os.path.exists(filepath):
                    self.log(f"文件不存在，无需删除: {os.path.basename(filepath)}")
                    return False

                line_count = self._get_file_line_count(filepath)
                if line_count == 0:
                    self.log(f"文件 {os.path.basename(filepath)} 没有数据行可删除")
                    return False

                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # 保留表头，删除最后一行数据
                lines = lines[:-1]

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

                self.log(f"已删除 {os.path.basename(filepath)} 的最新一行数据 (第{line_count}个点)")
                return True
            except Exception as e:
                self.log(f"删除文件 {filepath} 最新行失败: {e}")
                return False

    def delete_arm_latest_data(self, arm_type: str, identifier, display_name):
        data_dir = self._get_data_dir()

        if arm_type == "master":
            if identifier == "Left":
                mtm_file = os.path.join(data_dir, "mtm1_joint.cst")
            elif identifier == "Right":
                mtm_file = os.path.join(data_dir, "mtm2_joint.cst")
            else:
                return
            line_count = self._get_file_line_count(mtm_file)
            if line_count == 0:
                self.log(f"{display_name} 没有数据可删除")
                return
            # 弹出确认框，明确显示要删除第几行
            result = messagebox.askyesno("确认删除", f"确定要删除 {display_name} 的关节数据（第{line_count}个点）吗？\n此操作不可恢复。")
            if result:
                self.delete_last_line_with_prompt(mtm_file, f"{display_name} 关节数据")
                # 同时删除 view_angle 文件的最新行（如果有）
                view_file = os.path.join(data_dir, "view_angle.cst")
                if os.path.exists(view_file) and self._get_file_line_count(view_file) > 0:
                    self.delete_last_line_with_prompt(view_file, "view_angle")
            else:
                self.log(f"取消删除 {display_name} 数据")

        elif arm_type == "slave":
            arm_id = identifier
            psm_file = os.path.join(data_dir, f"psm{arm_id+1}_joint.cst")
            inst_file = os.path.join(data_dir, f"inst{arm_id+1}_joint.cst")
            line_count = self._get_file_line_count(psm_file)
            if line_count == 0:
                self.log(f"{display_name} 没有数据可删除")
                return
            result = messagebox.askyesno("确认删除", f"确定要删除 {display_name} 的最新数据（第{line_count}个点）吗？\n将同时删除前8关节和后4关节文件的最新行。")
            if result:
                self.delete_last_line_with_prompt(psm_file, f"{display_name} 前8关节")
                self.delete_last_line_with_prompt(inst_file, f"{display_name} 后4关节")
            else:
                self.log(f"取消删除 {display_name} 数据")

    def confirm_delete(self, arm_type, identifier, display_name):
        if (arm_type == "slave" and not self.slave_connected) or (arm_type == "master" and not self.master_connected):
            messagebox.showwarning("警告", f"{display_name} 未连接，无法删除数据")
            return
        # 直接调用删除函数（内部会再次确认并提示行号）
        threading.Thread(target=self.delete_arm_latest_data, args=(arm_type, identifier, display_name), daemon=True).start()

    # ---------- 刷新功能（只读取，不保存） ----------
    def refresh_arm(self, arm_type, identifier, is_batch=False):
        if arm_type == "slave" and not self.slave_connected:
            if not is_batch:
                messagebox.showwarning("警告", "从手未连接，无法刷新")
            return
        if arm_type == "master" and not self.master_connected:
            if not is_batch:
                messagebox.showwarning("警告", "主手未连接，无法刷新")
            return

        key = (arm_type, identifier)
        lbl_data, refresh_btn, _, _ = self.arm_widgets[key]
        refresh_btn.config(state=tk.DISABLED, text="刷新中...")
        display_name = f"{'从臂' if arm_type=='slave' else '主手'}{identifier}"
        self.log(f"正在刷新 {display_name}...")

        def task():
            if arm_type == "slave":
                data = self.ssh.read_slave(identifier)
            else:
                data = self.ssh.read_master(identifier)
            self.root.after(0, self.on_refresh_done, key, data, display_name, is_batch)

        threading.Thread(target=task, daemon=True).start()

    def on_refresh_done(self, key, data, display_name, is_batch):
        lbl_data, refresh_btn, _, _ = self.arm_widgets[key]
        refresh_btn.config(state=tk.NORMAL, text="刷新")

        if data is None:
            lbl_data.config(text="读取失败", foreground="red")
            self.log(f"{display_name} 读取失败")
        else:
            if isinstance(data, SlaveData):
                angles = data.cur_pos
                angle_str = ", ".join([f"{a:.5f}" for a in angles])
                # 刷新时不保存，仅更新显示
            else:  # MasterData
                angles = data.cur_q
                angle_str = ", ".join([f"{a:.4f}" for a in angles])
                # 刷新时自动保存 view_angle（因为 view_angle 需要实时捕获并保存）
                if data.view_angle is not None:
                    self.save_view_angle_to_file(data.view_angle)

            lbl_data.config(text=angle_str, foreground="black")
            self.log(f"{display_name} 刷新完成 - {data.timestamp}")

        if is_batch:
            self.batch_refresh_count -= 1
            if self.batch_refresh_count == 0:
                self.log("所有机械臂刷新完成")

    def refresh_all(self):
        if not self.slave_connected and not self.master_connected:
            messagebox.showwarning("警告", "没有可用的连接")
            return

        total = 0
        for (arm_type, _), _ in self.arm_widgets.items():
            if (arm_type == "slave" and self.slave_connected) or (arm_type == "master" and self.master_connected):
                total += 1

        if total == 0:
            self.log("没有可刷新的机械臂")
            return

        self.batch_refresh_total = total
        self.batch_refresh_count = total
        self.log(f"开始批量刷新 {total} 个机械臂...")

        for (arm_type, identifier), _ in self.arm_widgets.items():
            if (arm_type == "slave" and self.slave_connected) or (arm_type == "master" and self.master_connected):
                self.refresh_arm(arm_type, identifier, is_batch=True)

    # ---------- 连接 ----------
    def do_connect(self):
        slave_ip = self.slave_ip.get().strip()
        slave_user = self.slave_user.get().strip()
        slave_pwd = self.slave_pwd.get().strip()
        master_ip = self.master_ip.get().strip()
        master_user = self.master_user.get().strip()
        master_pwd = self.master_pwd.get().strip()

        if not slave_ip or not slave_user or not slave_pwd:
            messagebox.showerror("错误", "请完整填写从手电脑的IP、用户名和密码")
            return
        if not master_ip or not master_user or not master_pwd:
            messagebox.showerror("错误", "请完整填写主手电脑的IP、用户名和密码")
            return

        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.log("正在连接主手和从手...")

        def connect_task():
            slave_ok = self.ssh.connect_slave(slave_ip, slave_user, slave_pwd)
            master_ok = self.ssh.connect_master(master_ip, master_user, master_pwd)
            self.root.after(0, self.on_connect_result, slave_ok, master_ok)

        threading.Thread(target=connect_task, daemon=True).start()

    def on_connect_result(self, slave_ok, master_ok):
        self.connect_btn.config(state=tk.NORMAL, text="连接")
        self.slave_connected = slave_ok
        self.master_connected = master_ok

        if slave_ok and master_ok:
            self.status_label.config(text="全部已连接", foreground="green")
            self.log("主手和从手连接均成功！")
            self.refresh_all_btn.config(state=tk.NORMAL)
            for (arm_type, _), (_, refresh_btn, save_btn, delete_btn) in self.arm_widgets.items():
                if (arm_type == "slave" and slave_ok) or (arm_type == "master" and master_ok):
                    refresh_btn.config(state=tk.NORMAL)
                    save_btn.config(state=tk.NORMAL)
                    delete_btn.config(state=tk.NORMAL)
        else:
            msg = []
            if not slave_ok:
                msg.append("从手连接失败")
            if not master_ok:
                msg.append("主手连接失败")
            self.status_label.config(text="部分连接失败", foreground="orange")
            self.log(f"连接结果: {', '.join(msg)}")
            for (arm_type, _), (_, refresh_btn, save_btn, delete_btn) in self.arm_widgets.items():
                can_enable = (arm_type == "slave" and slave_ok) or (arm_type == "master" and master_ok)
                refresh_btn.config(state=tk.NORMAL if can_enable else tk.DISABLED)
                save_btn.config(state=tk.NORMAL if can_enable else tk.DISABLED)
                delete_btn.config(state=tk.NORMAL if can_enable else tk.DISABLED)

    # ---------- 运行 ----------
    def run(self):
        self.root.mainloop()

    def on_closing(self):
        self.ssh.disconnect_all()
        self.root.destroy()


if __name__ == "__main__":
    app = SimpleMonitor()
    app.run()