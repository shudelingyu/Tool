#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运动学自动辨识工具 (PyQt5版)
- SSH远程连接到远端
- 自动摆位控制（从臂1-4）
- 读取identifytrajectory路点文件并执行
"""

import re
import os
import sys
import threading
import socket
import struct
import paramiko
import math
from datetime import datetime
from typing import Optional, List, Tuple, Dict

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPlainTextEdit, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor


# ==================== 配色方案 ====================
C = {
    "indigo":    "#4F46E5",
    "indigo_dk": "#3730A3",
    "indigo_lt": "#818CF8",
    "indigo_md": "#6366F1",
    "slate":     "#1E293B",
    "slate_md":  "#475569",
    "slate_lt":  "#94A3B8",
    "bg":        "#F1F5F9",
    "card":      "#FFFFFF",
    "green":     "#10B981",
    "red":       "#EF4444",
    "amber":     "#F59E0B",
    "border":    "#E2E8F0",
}

# 摆位按钮配色
ARM_COLORS = [
    {"bg": "#3B82F6", "hover": "#2563EB", "icon": "❶"},
    {"bg": "#F59E0B", "hover": "#D97706", "icon": "❷"},
    {"bg": "#8B5CF6", "hover": "#7C3AED", "icon": "❸"},
    {"bg": "#10B981", "hover": "#059669", "icon": "❹"},
]

# ==================== SSH 凭证（硬编码） ====================
SSH_USER = "codeit"
SSH_PASS = "1"

# ==================== 执行路点 ====================
# 指令格式: {model0||model1||Boom||从臂1||从臂2||从臂3||从臂4}
# 主手格式: {左手||右手}
ARM_CFG = {
    1: {"pos": 3, "num": 8},
    2: {"pos": 4, "num": 8},
    3: {"pos": 5, "num": 8},
    4: {"pos": 6, "num": 8},
}

# 从臂执行路点的7条指令模板
SLAVE_EXEC_TEMPLATE = [
    "URecover",
    "Mode",
    "UEnable --begin_motion_id=0 --num={num}",
    "URecover",
    "MoveAbsolute --num={num} --pos={{{wp}}} --vel={{0.05}} --acc={{0.05}} --jerk={{0.1}}",
    "URecover",
    "UDisable --begin_motion_id=0 --num={num}",
]


def _slot_cmd(arm_id: int, cmd: str) -> str:
    """将指令放入对应臂的槽位，其余为Idle"""
    pos = ARM_CFG[arm_id]["pos"]
    parts = ["Idle"] * 7
    parts[pos] = cmd
    return "{" + "||".join(parts) + "}"

# ==================== 自动摆位命令配置 ====================

# 从 Positioning 文件读取四臂的摆位数据
def _load_positioning(path: str = None) -> Dict[int, List[float]]:
    if path is None:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "Positioning")
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, vals = line.split(":", 1)
                if key.startswith("arm"):
                    arm_id = int(key.replace("arm", ""))
                    result[arm_id] = [float(v) for v in vals.strip().split()]
    except Exception as e:
        print(f"加载 Positioning 失败: {e}")
    return result

POS_DATA = _load_positioning()

def _fmt_pos(arm_id: int) -> str:
    """将 Positioning 数据格式化为 花括号包裹逗号分隔"""
    data = POS_DATA.get(arm_id, [])
    return "{" + ",".join(f"{v:.6f}" for v in data) + "}"

def _build_press_cmds(arm_id: int) -> List[str]:
    """构建按住时下发的8条指令"""

    def _all(cmd: str) -> str:
        """所有臂位置(2-6)设为相同命令"""
        return f"{{Idle||Idle||{cmd}||{cmd}||{cmd}||{cmd}||{cmd}}}"

    cmds = []
    cmds.append(_all("URecover"))                                    # 1
    cmds.append(_all("Mode"))                                        # 2
    cmds.append(                                                      # 3
        f"{{Idle||Idle||UEnable --begin_motion_id=0 --num=4"
        f"||UEnable --begin_motion_id=0 --num=8"
        f"||UEnable --begin_motion_id=0 --num=8"
        f"||UEnable --begin_motion_id=0 --num=8"
        f"||UEnable --begin_motion_id=0 --num=8}}"
    )
    cmds.append(_all("URecover"))                                    # 4
    # 5: 仅选中臂用 Positioning 数据，其余 UEmpty
    cmds.append(f"{{Idle||Idle||AutoPositionPlanning --mode=2.0 --custom_pos={_fmt_pos(arm_id)}"
        f"||UEmpty"
        f"||UEmpty"
        f"||UEmpty"
        f"||UEmpty}}")
    cmds.append(_all("AutoPositionRunning"))                          # 6
    cmds.append(_all("URecover"))                                  # 7
    cmds.append(                                                      # 8
        f"{{Idle||Idle||UDisable --begin_motion_id=0 --num=4"
        f"||UDisable --begin_motion_id=0 --num=8"
        f"||UDisable --begin_motion_id=0 --num=8"
        f"||UDisable --begin_motion_id=0 --num=8"
        f"||UDisable --begin_motion_id=0 --num=8}}"
    )
    return cmds


def _build_release_cmds() -> List[str]:
    """构建松开时下发的指令"""
    all_stop = "{PushStatus||PushStatus||PushStatus --mode_id=0 --motion_cmd=0||PushStatus --mode_id=1 --motion_cmd=0||PushStatus --mode_id=2 --motion_cmd=0||PushStatus --mode_id=3 --motion_cmd=0||PushStatus --mode_id=4 --motion_cmd=0}"
    all_start = "{PushStatus||PushStatus||PushStatus --mode_id=0 --motion_cmd=1||PushStatus --mode_id=1 --motion_cmd=1||PushStatus --mode_id=2 --motion_cmd=1||PushStatus --mode_id=3 --motion_cmd=1||PushStatus --mode_id=4 --motion_cmd=1}"
    return [all_stop, all_start]


def _build_slave_exec_cmds(arm_id: int, angles: List[float]) -> List[str]:
    """构建从手执行路点的7条指令，angles为关节角度列表"""
    num = ARM_CFG[arm_id]["num"]
    angle_str = ",".join(f"{a:.4f}" for a in angles)
    cmds = []
    for template in SLAVE_EXEC_TEMPLATE:
        cmd = template.format(num=num, wp=angle_str)
        cmds.append(_slot_cmd(arm_id, cmd))
    return cmds


def _build_master_exec_cmd(angles: List[float], hand: int = 0) -> str:
    """构建主手执行路点的单条指令  hand=0左, 1右, angles为关节角度列表"""
    angle_str = "{" + ",".join(f"{a:.4f}" for a in angles) + "}"
    if hand == 0:
        return f"{{MtmMoveP --pos={angle_str}||Idle}}"
    else:
        return f"{{Idle||MtmMoveP --pos={angle_str}}}"

# ==================== 全局样式表 ====================
STYLESHEET = f"""
QWidget {{
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 9pt;
    color: {C['slate']};
}}

/* ── 标题栏 ── */
#headerBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C['indigo']}, stop:1 {C['indigo_dk']});
    min-height: 60px; max-height: 60px; border: none;
}}

/* ── 卡片容器 ── */
Card {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}

#cardTitle {{
    font-size: 11pt; font-weight: bold; color: {C['slate']};
    padding: 0; margin: 0;
}}

/* ── 输入框 ── */
QLineEdit {{
    border: 1.5px solid {C['border']};
    border-radius: 6px; padding: 6px 10px;
    background: {C['card']}; color: {C['slate']};
    selection-background-color: {C['indigo_lt']};
    font-size: 9pt;
}}
QLineEdit:focus {{
    border-color: {C['indigo']};
}}

/* ── 按钮通用 ── */
QPushButton {{
    border: none; border-radius: 6px;
    padding: 7px 18px; font-weight: bold; font-size: 9pt;
}}
QPushButton::disabled {{
    background: #CBD5E1 !important;
    color: #94A3B8 !important;
}}

/* ── 连接按钮 ── */
#connectBtn {{
    background: {C['indigo']}; color: white; padding: 7px 28px;
    border-radius: 8px; font-size: 10pt;
}}
#connectBtn:hover {{ background: {C['indigo_dk']}; }}
#connectBtn:pressed {{ background: {C['indigo_dk']}; }}

/* ── 加载文件按钮 ── */
#loadBtn {{
    background: {C['slate_md']}; color: white; border-radius: 6px;
}}
#loadBtn:hover {{ background: {C['slate']}; }}

/* ── 执行按钮 ── */
#execBtn {{
    background: {C['green']}; color: white; padding: 9px 30px;
    border-radius: 8px; font-size: 10pt;
}}
#execBtn:hover {{ background: #059669; }}
#execBtn:pressed {{ background: #047857; }}

/* ── 状态灯 ── */
#statusLight {{
    border-radius: 7px;
    min-width: 14px; max-width: 14px;
    min-height: 14px; max-height: 14px;
}}

/* ── 表格 ── */
QTableWidget {{
    border: 1px solid {C['border']};
    border-radius: 6px; gridline-color: {C['border']};
    background: {C['card']};
    selection-background-color: #EEF2FF;
    selection-color: {C['slate']};
    font-size: 9pt;
}}
QTableWidget::item {{
    padding: 6px 10px; border-bottom: 1px solid {C['border']};
}}
QTableWidget::item:selected {{
    background: {C['green']}; color: white;
    font-weight: bold;
}}
QHeaderView::section {{
    background: #F8FAFC; color: {C['slate_md']};
    font-weight: bold; font-size: 9pt;
    border: none; border-bottom: 2px solid {C['indigo_lt']};
    padding: 8px 10px;
}}

/* ── 日志区域 ── */
#logEdit {{
    background: #FFFFFF; color: #1E293B;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 9pt; border: 1px solid {C['border']}; border-radius: 6px;
    padding: 6px; selection-background-color: {C['indigo_lt']};
}}
"""


# ==================== 摆位按钮组件 ====================
class PosButton(QPushButton):
    """自定义按钮，精确控制鼠标按下/松开事件"""
    press_arm = pyqtSignal(int)
    release_arm = pyqtSignal(int)

    def __init__(self, arm_id, parent=None):
        super().__init__(parent)
        self._arm_id = arm_id

    def mousePressEvent(self, event):
        self.press_arm.emit(self._arm_id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.release_arm.emit(self._arm_id)
        super().mouseReleaseEvent(event)


# ==================== 卡片组件 ====================
class Card(QFrame):
    """卡片容器 — 带标题的圆角白色卡片"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            Card {{ background: {C['card']}; border: 1px solid {C['border']};
                    border-radius: 10px; }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

        if title:
            title_lbl = QLabel(title)
            title_lbl.setObjectName("cardTitle")
            self._layout.addWidget(title_lbl)

        self._content = QVBoxLayout()
        self._content.setSpacing(8)
        self._layout.addLayout(self._content)

    def addLayout(self, layout):
        self._content.addLayout(layout)

    def addWidget(self, widget):
        self._content.addWidget(widget)


# ==================== TCP客户端 ====================
class TcpClient:
    """TCP 套接字连接客户端（仿 InstTool.py）"""

    def __init__(self, log_callback=None):
        self.sock: Optional[socket.socket] = None
        self.log_callback = log_callback
        self.connected = False

    def _log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)

    def connect(self, host: str, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            self.sock = sock
            self.connected = True
            self._log(f"TCP连接成功 {host}:{port}")
            return True
        except socket.timeout:
            self._log("连接超时")
            return False
        except ConnectionRefusedError:
            self._log("连接被拒绝")
            return False
        except Exception as e:
            self._log(f"连接失败: {type(e).__name__}: {e}")
            return False

    @staticmethod
    def _encode_message(data: str) -> bytes:
        """按 InstTool 协议格式编码: 4字节长度 + 36字节填充 + 数据"""
        data_bytes = data.encode("utf-8")
        head = struct.pack("<I", len(data_bytes))
        pad = bytes([0] * 36)
        return head + pad + data_bytes

    @staticmethod
    def _decode_message(buf: bytes) -> Tuple[Optional[str], bytes]:
        """尝试从缓冲区解析一条协议消息，返回 (消息内容, 剩余数据)"""
        if len(buf) < 40:
            return None, buf
        data_len = struct.unpack("<I", buf[:4])[0]
        if len(buf) < 40 + data_len:
            return None, buf
        payload = buf[40:40 + data_len]
        text = payload.decode("utf-8", errors="replace").strip("\x00").strip()
        return text, buf[40 + data_len:]

    def send_and_recv(self, data: str, timeout: float = 3.0, expected: int = 0) -> Tuple[str, str]:
        """发送指令并等待全部 model 回复，返回 (全部回复, 错误信息)
           expected: 期望回复条数，0 自动根据 || 数量推断"""
        if not self.sock or not self.connected:
            return "", "未连接"

        if expected <= 0:
            expected = data.count("||") + 1

        try:
            self.sock.sendall(self._encode_message(data))
            self.sock.settimeout(timeout)
            buf = b""
            replies = []
            while len(replies) < expected:
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    return "\n".join(replies), f"超时 (已收 {len(replies)}/{expected})"
                if not chunk:
                    break
                buf += chunk
                while True:
                    msg, buf = self._decode_message(buf)
                    if msg is None:
                        break
                    replies.append(msg)
                if len(buf) > 1_000_000:
                    return "\n".join(replies), "响应过大"
            return "\n".join(replies), ""
        except (ConnectionError, OSError) as e:
            err_msg = f"接收失败: {type(e).__name__}: {e}"
            self._log(err_msg)
            return "", err_msg

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
        self._log("TCP连接已断开")


# ==================== SSH客户端（复刻 JointMonitor） ====================
class SSHReader:
    """通过 SSH 读取远程日志获取实际关节角（同 JointMonitor）"""

    def __init__(self, log_callback=None):
        self.slave_client: Optional[paramiko.SSHClient] = None
        self.master_client: Optional[paramiko.SSHClient] = None
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def connect_slave(self, ip: str, username: str, password: str, port: int = 22) -> bool:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=ip, port=port, username=username, password=password, timeout=5)
            self.slave_client = client
            self._log(f"SSH从手连接成功 {ip}")
            return True
        except Exception as e:
            self._log(f"SSH从手连接失败: {e}")
            return False

    def connect_master(self, ip: str, username: str, password: str, port: int = 22) -> bool:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=ip, port=port, username=username, password=password, timeout=5)
            self.master_client = client
            self._log(f"SSH主手连接成功 {ip}")
            return True
        except Exception as e:
            self._log(f"SSH主手连接失败: {e}")
            return False

    def get_last_line(self, client: paramiko.SSHClient, log_path: str) -> Optional[str]:
        try:
            _, stdout, stderr = client.exec_command(f'test -f "{log_path}" && echo "exists" || echo "not_exists"')
            check_result = stdout.read().decode('utf-8', errors='ignore').strip()
            if check_result != "exists":
                self._log(f"日志文件不存在 - {log_path}")
                return None

            _, stdout, stderr = client.exec_command(f'tail -n 1 "{log_path}" 2>&1')
            line = stdout.read().decode('utf-8', errors='ignore').strip()
            error_msg = stderr.read().decode('utf-8', errors='ignore').strip()
            if error_msg:
                self._log(f"读取文件失败 {log_path}: {error_msg}")
                return None

            if not line or len(line) < 10:
                _, stdout2, _ = client.exec_command(f'tail -n 2 "{log_path}" 2>&1 | head -n 1')
                line2 = stdout2.read().decode('utf-8', errors='ignore').strip()
                if line2 and len(line2) >= 10:
                    return line2
                else:
                    self._log(f"警告：日志文件内容过短或为空 - {log_path}")
                    return None
            return line
        except Exception as e:
            self._log(f"读取文件异常 {log_path}: {type(e).__name__}: {e}")
            return None

    def parse_slave_log(self, log_line: str, arm_id: int) -> Optional[List[float]]:
        """解析从臂日志，返回 12 个关节角或 None"""
        if not log_line:
            return None
        parts = [p.strip() for p in log_line.split(',') if p.strip() != '']
        if not parts:
            return None
        cur_pos = [0.0] * 12
        if len(parts) < 100:
            # 简化格式
            if len(parts) >= 16:
                try:
                    for i, val in enumerate(parts[9:16]):
                        cur_pos[5 + i] = float(val)
                    self._log(f"从臂{arm_id} 简化格式 (关节5-12)")
                    return cur_pos
                except ValueError:
                    pass
            self._log(f"从臂{arm_id} 简化格式数据不足")
        else:
            # 完整格式
            if len(parts) >= 26:
                try:
                    cur_pos = [float(v) for v in parts[14:26]]
                    self._log(f"从臂{arm_id} 完整格式 (13个关节)")
                    return cur_pos
                except ValueError:
                    pass
            self._log(f"从臂{arm_id} 完整格式数据不足")
        return None

    def parse_master_log(self, log_line: str, arm_name: str) -> Tuple[Optional[List[float]], Optional[float]]:
        """解析主手日志，返回 (7关节角, view_angle)"""
        if not log_line:
            return None, None
        self._log(f"解析主手 {arm_name} 日志")

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
        j7 = math.remainder(j7, 2 * math.pi)
        result[6] = j7

        view_angle = None
        view_pattern = r'view_angle\s+([\d.-]+)'
        match_view = re.search(view_pattern, log_line)
        if match_view:
            view_angle = float(match_view.group(1))

        return result, view_angle

    def read_slave(self, arm_id: int) -> Optional[List[float]]:
        """读取从臂 arm_id 的当前关节角"""
        if not self.slave_client:
            return None
        log_path = f"/data/log/rt/mmsArm{arm_id}/mmsArm{arm_id}"
        line = self.get_last_line(self.slave_client, log_path)
        if line:
            return self.parse_slave_log(line, arm_id)
        return None

    def read_master(self, arm_name: str) -> Tuple[Optional[List[float]], Optional[float]]:
        """读取主手的当前关节角和 view_angle"""
        if not self.master_client:
            return None, None
        log_path = f"/data/log/rt/{arm_name}DataModel/{arm_name}DataModel"
        line = self.get_last_line(self.master_client, log_path)
        if line:
            return self.parse_master_log(line, arm_name)
        return None, None

    def disconnect_all(self):
        if self.slave_client:
            self.slave_client.close()
            self.slave_client = None
        if self.master_client:
            self.master_client.close()
            self.master_client = None
        self._log("SSH连接已断开")


# ==================== 主窗口 ====================
class AutoKinematicsWindow(QWidget):
    """运动学自动辨识工具主窗口"""

    # 线程安全信号
    signal_connect_result = pyqtSignal(bool, bool, bool)  # tcp, ssh_slave, ssh_master
    signal_auto_pos_done = pyqtSignal(int)
    signal_file_loaded = pyqtSignal(list)
    signal_exec_done = pyqtSignal()
    signal_log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("运动学自动辨识工具")
        self.resize(1000, 760)
        self._center()

        # TCP
        self.tcp = TcpClient(log_callback=self._log)
        self.connected = False

        # SSH
        self.ssh = SSHReader(log_callback=self._log)
        self.ssh_slave_connected = False
        self.ssh_master_connected = False

        self.waypoints: List[Tuple[str, List[float]]] = []

        # 模式: 0=主手, 1=从手
        self.mode = 1
        self.model = 7

        # 自动摆位状态（每条臂一个线程标志）
        self.pos_running = {i: False for i in range(1, 5)}
        self.pos_lock = threading.Lock()

        # 信号连接
        self.signal_connect_result.connect(self._on_connect_result)
        self.signal_auto_pos_done.connect(self._on_auto_pos_done)
        self.signal_file_loaded.connect(self._on_file_loaded)
        self.signal_exec_done.connect(self._on_exec_done)
        self.signal_log.connect(self._append_log)

        self.data_dir = self._get_data_dir()
        self.file_locks = {}

        self._setup_ui()

    # ---------- 窗口 ----------
    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - 1000) // 2, (screen.height() - 760) // 2)

    # ---------- UI构建 ----------
    def _setup_ui(self):
        self.setStyleSheet(STYLESHEET)

        # 全局背景色
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(C["bg"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ========== 标题栏 ==========
        header = QFrame()
        header.setObjectName("headerBar")
        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(24, 0, 24, 0)

        title = QLabel("⚙运动学自动辨识工具")
        title.setStyleSheet("color: white; font-size: 15pt; font-weight: bold; letter-spacing: 1px;")
        hdr.addWidget(title)

        hdr.addStretch()

        subtitle = QLabel(f"Made with TC❤️  |  {datetime.now().strftime('%Y-%m-%d')}")
        subtitle.setStyleSheet("color: #A5B4FC; font-size: 8pt;")
        hdr.addWidget(subtitle)

        root.addWidget(header)

        # ========== 主体 ==========
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(14)

        # ── 连接卡片 ──
        body.addWidget(self._build_connect_card())

        # ── 左右分栏 ──
        cols = QHBoxLayout()
        cols.setSpacing(14)
        self.pos_card = self._build_pos_card()
        cols.addWidget(self.pos_card, stretch=2)
        cols.addWidget(self._build_waypoint_card(), stretch=3)
        body.addLayout(cols, stretch=1)

        # ── 日志卡片 ──
        log_card = Card("📝 运行日志")
        log_card.setMaximumHeight(180)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("logEdit")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(1000)
        log_card.addWidget(self.log_edit)
        body.addWidget(log_card)

        root.addLayout(body)

        # 默认值已在输入框构造时设置

    # ---------- 连接卡片 ----------
    def _build_connect_card(self):
        card = Card("🔗 远程连接")

        row = QHBoxLayout()
        row.setSpacing(2)

        self.ip_edit = QLineEdit("192.168.11.11")
        self.ip_edit.setFixedWidth(140)
        self.ip_edit.setFont(QFont("Consolas", 9))
        row.addWidget(self._labeled_widget("主机IP", self.ip_edit))
        row.addSpacing(2)

        self.port_edit = QLineEdit("7866")
        self.port_edit.setFixedWidth(70)
        self.port_edit.setFont(QFont("Consolas", 9))
        row.addWidget(self._labeled_widget("端口", self.port_edit))
        row.addSpacing(10)

        self.connect_btn = QPushButton("🔗 连接")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.clicked.connect(self._do_connect)
        row.addWidget(self.connect_btn)
        row.addSpacing(6)

        self.status_light = QFrame()
        self.status_light.setObjectName("statusLight")
        self.status_light.setStyleSheet(f"background: #CBD5E1; border-radius: 7px;")
        row.addWidget(self.status_light)
        row.addSpacing(4)

        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet(f"color: {C['slate_lt']}; font-size: 9pt;")
        row.addWidget(self.status_label)
        row.addSpacing(16)

        # ── 主手/从手切换 ──
        row.addWidget(QLabel("模式:"))
        self.mode_btn_master = QPushButton("主手")
        self.mode_btn_master.setCheckable(True)
        self.mode_btn_master.setFixedWidth(60)
        self.mode_btn_master.clicked.connect(lambda: self._set_mode(0))
        self.mode_btn_slave = QPushButton("从手")
        self.mode_btn_slave.setCheckable(True)
        self.mode_btn_slave.setFixedWidth(60)
        self.mode_btn_slave.setChecked(True)
        self.mode_btn_slave.clicked.connect(lambda: self._set_mode(1))
        self._style_mode_buttons()
        row.addWidget(self.mode_btn_master)
        row.addWidget(self.mode_btn_slave)

        row.addStretch()

        card.addLayout(row)

        return card

    @staticmethod
    def _labeled_widget(label: str, widget: QWidget) -> QWidget:
        """带标签的输入框"""
        container = QFrame()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C['slate_md']}; font-size: 9pt; white-space: nowrap;")
        layout.addWidget(lbl)
        layout.addWidget(widget)
        return container

    # ---------- 摆位卡片 ----------
    def _build_pos_card(self):
        card = Card("🎯 自动摆位")
        grid = QGridLayout()
        grid.setSpacing(12)

        self.pos_btns = []
        for i in range(4):
            ac = ARM_COLORS[i]
            btn = PosButton(i + 1)
            btn.setMinimumSize(0, 90)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._pos_css(i, enabled=False))
            btn.setEnabled(False)
            btn.press_arm.connect(self._start_auto_position)
            btn.release_arm.connect(self._stop_auto_position)

            # 按钮内用垂直布局排列图标+文字
            bl = QVBoxLayout()
            bl.setContentsMargins(8, 8, 8, 8)
            bl.setSpacing(2)
            bl.addStretch()
            icon = QLabel(ac["icon"])
            icon.setAlignment(Qt.AlignCenter)
            icon.setAttribute(Qt.WA_TransparentForMouseEvents)
            icon.setStyleSheet("font-size: 22px; color: white; background: transparent;")
            bl.addWidget(icon)
            txt = QLabel(f"从臂{i+1}\n自动摆位")
            txt.setAlignment(Qt.AlignCenter)
            txt.setAttribute(Qt.WA_TransparentForMouseEvents)
            txt.setStyleSheet("color: white; font-size: 10pt; font-weight: bold; background: transparent;")
            bl.addWidget(txt)
            bl.addStretch()
            btn.setLayout(bl)

            row, col = i // 2, i % 2
            grid.addWidget(btn, row, col)
            self.pos_btns.append(btn)

        card.addLayout(grid)
        return card

    def _pos_css(self, idx: int, enabled: bool = True, busy: bool = False) -> str:
        ac = ARM_COLORS[idx]
        if busy:
            bg, hov = "#94A3B8", "#94A3B8"
        elif not enabled:
            bg, hov = "#CBD5E1", "#CBD5E1"
        else:
            bg, hov = ac["bg"], ac["hover"]
        return (
            f"QPushButton {{ background: {bg}; border: none; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {hov}; }}"
            f"QPushButton:pressed {{ background: {hov}; }}"
            f"QPushButton::disabled {{ background: #CBD5E1; }}"
        )

    # ---------- 路点卡片 ----------
    def _build_waypoint_card(self):
        card = Card("📋 路点管理")

        # 文件选择
        file_row = QHBoxLayout()
        self.file_label = QLabel("未选择路点文件")
        self.file_label.setStyleSheet(f"color: {C['slate_lt']}; font-size: 8pt;")
        file_row.addWidget(self.file_label, stretch=1)

        self.load_btn = QPushButton("📂 加载文件")
        self.load_btn.setObjectName("loadBtn")
        self.load_btn.clicked.connect(self._load_trajectory_file)
        file_row.addWidget(self.load_btn)
        card.addLayout(file_row)

        # ── 执行目标选择 ──
        self.target_frame = QFrame()
        target_row = QHBoxLayout(self.target_frame)
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(4)

        self.target_label = QLabel("执行于:")
        self.target_label.setStyleSheet(f"color: {C['slate_md']}; font-size: 8pt; font-weight: bold;")
        target_row.addWidget(self.target_label)

        # 从手臂选择按钮
        self.arm_target_btns = []
        arm_labels = ["❶ 从臂1", "❷ 从臂2", "❸ 从臂3", "❹ 从臂4"]
        for i in range(4):
            btn = QPushButton(arm_labels[i])
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(self._target_btn_css(selected=(i == 0)))
            btn.clicked.connect(lambda _, a=i+1: self._select_arm_target(a))
            target_row.addWidget(btn)
            self.arm_target_btns.append(btn)
        self.arm_target_btns[0].setChecked(True)

        # 主手左右选择按钮
        self.hand_target_btns = []
        for i, label in enumerate(["👈 左手", "👉 右手"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(self._target_btn_css(selected=(i == 0)))
            btn.clicked.connect(lambda _, h=i: self._select_hand_target(h))
            target_row.addWidget(btn)
            self.hand_target_btns.append(btn)
        self.hand_target_btns[0].setChecked(True)

        target_row.addStretch()
        card.addWidget(self.target_frame)

        # 存储选中状态
        self.selected_arm = 1
        self.selected_hand = 0
        self._refresh_target_visibility()

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["路点名称", "关节角度"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        card.addWidget(self.table)

        # 底部操作行
        exec_row = QHBoxLayout()
        self.wp_count_label = QLabel("共 0 个路点")
        self.wp_count_label.setStyleSheet(f"color: {C['slate_lt']};")
        exec_row.addWidget(self.wp_count_label)
        exec_row.addStretch()

        self.exec_btn = QPushButton("▶执行路点")
        self.exec_btn.setObjectName("execBtn")
        self.exec_btn.setEnabled(False)
        self.exec_btn.clicked.connect(self._execute_waypoint)
        exec_row.addWidget(self.exec_btn)
        exec_row.addSpacing(6)

        self.stop_btn = QPushButton("🛑急停")
        self.stop_btn.setStyleSheet(
            f"background: {C['red']}; color: white; border-radius: 8px; "
            f"padding: 9px 24px; font-size: 10pt; font-weight: bold;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._emergency_stop)
        exec_row.addWidget(self.stop_btn)
        exec_row.addSpacing(6)

        self.save_btn = QPushButton("💾 保存数据")
        self.save_btn.setStyleSheet(
            f"background: {C['indigo']}; color: white; border-radius: 8px; "
            f"padding: 9px 18px; font-size: 10pt; font-weight: bold;"
        )
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_after_waypoint)
        exec_row.addWidget(self.save_btn)
        card.addLayout(exec_row)

        return card

    # ---------- 日志 ----------
    def _log(self, msg: str):
        self.signal_log.emit(msg)

    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{ts}] {msg}")

    # ---------- 目标选择辅助 ----------
    def _target_btn_css(self, selected: bool = False) -> str:
        if selected:
            return f"background: {C['indigo']}; color: white; border: none; border-radius: 4px; padding: 4px 10px; font-size: 8pt;"
        else:
            return f"background: {C['card']}; color: {C['slate_md']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 10px; font-size: 8pt;"

    def _select_arm_target(self, arm_id: int):
        self.selected_arm = arm_id
        for i, btn in enumerate(self.arm_target_btns):
            btn.setChecked(i + 1 == arm_id)
            btn.setStyleSheet(self._target_btn_css(i + 1 == arm_id))

    def _select_hand_target(self, hand: int):
        self.selected_hand = hand
        for i, btn in enumerate(self.hand_target_btns):
            btn.setChecked(i == hand)
            btn.setStyleSheet(self._target_btn_css(i == hand))

    def _refresh_target_visibility(self):
        """根据当前模式显示对应目标选择器"""
        if not hasattr(self, 'arm_target_btns'):
            return
        show_arm = (self.mode == 1)
        show_hand = (self.mode == 0)
        self.target_label.setText("执行于:" if show_arm else "手:")
        for btn in self.arm_target_btns:
            btn.setVisible(show_arm)
        for btn in self.hand_target_btns:
            btn.setVisible(show_hand)

    # ---------- 模式切换 ----------
    def _style_mode_buttons(self):
        """更新模式按钮样式"""
        active = f"background: {C['indigo']}; color: white; border: 1px solid {C['indigo']}; border-radius: 4px; padding: 4px 10px; font-size: 8pt;"
        inactive = f"background: {C['card']}; color: {C['slate_md']}; border: 1px solid {C['border']}; border-radius: 4px; padding: 4px 10px; font-size: 8pt;"
        self.mode_btn_master.setStyleSheet(active if self.mode == 0 else inactive)
        self.mode_btn_slave.setStyleSheet(active if self.mode == 1 else inactive)

    def _set_mode(self, mode: int):
        """切换主手/从手模式"""
        self.mode = mode
        self.model = 7 if self.mode == 1 else 2
        self.mode_btn_master.setChecked(mode == 0)
        self.mode_btn_slave.setChecked(mode == 1)
        self._style_mode_buttons()

        # 主手隐藏摆位卡片，从手显示
        if hasattr(self, 'pos_card'):
            self.pos_card.setVisible(mode == 1)

        self._refresh_target_visibility()
        self._update_exec_btn()
        mode_name = "主手" if mode == 0 else "从手"
        self._log(f"切换至{mode_name}模式,model:{self.model}")

        # 如果已连接，自动重连对应模式的 SSH
        if self.connected:
            self._reconnect_ssh_for_mode()

    # ---------- 连接管理 ----------
    def _update_ui_state(self):
        for i, btn in enumerate(self.pos_btns):
            btn.setEnabled(self.connected)
            btn.setStyleSheet(self._pos_css(i, enabled=self.connected))
        self._update_exec_btn()

    def _update_exec_btn(self):
        has_data = len(self.waypoints) > 0
        self.exec_btn.setEnabled(self.connected and has_data)
        self.stop_btn.setEnabled(self.connected)
        self.save_btn.setEnabled(has_data)
        # if self.mode == 0:
        #     self.exec_btn.setText("▶ MtmMoveP执行")
        # else:
        #     self.exec_btn.setText("▶ MoveAbs执行")

    def _reconnect_ssh_for_mode(self):
        """根据当前模式重新连接 SSH（切模式时调用，复用 TCP IP + 硬编码凭证）"""
        old_slave = self.ssh_slave_connected
        old_master = self.ssh_master_connected
        ip = self.ip_edit.text().strip()

        # 断开旧 SSH
        if self.mode == 1 and old_master:
            self.ssh.master_client = None
            self.ssh_master_connected = False
        elif self.mode == 0 and old_slave:
            self.ssh.slave_client = None
            self.ssh_slave_connected = False

        def task():
            if self.mode == 1:
                self._log("切换至从手模式，连接 SSH 从手...")
                ok = self.ssh.connect_slave(ip, SSH_USER, SSH_PASS)
                self.ssh_slave_connected = ok
            else:
                self._log("切换至主手模式，连接 SSH 主手...")
                ok = self.ssh.connect_master(ip, SSH_USER, SSH_PASS)
                self.ssh_master_connected = ok
            s = "✓" if ok else "✗"
            mode_name = "从手" if self.mode == 1 else "主手"
            self._log(f"SSH{mode_name}重连{s}")

        threading.Thread(target=task, daemon=True).start()

    def _do_connect(self):
        if self.connected:
            self.tcp.disconnect()
            self.ssh.disconnect_all()
            self.connected = False
            self.ssh_slave_connected = False
            self.ssh_master_connected = False
            self.connect_btn.setText("🔗 连接")
            self.status_light.setStyleSheet(f"background: #CBD5E1; border-radius: 7px;")
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet(f"color: {C['slate_lt']};")
            self._update_ui_state()
            self._log("已断开连接")
            return

        ip = self.ip_edit.text().strip()
        port_str = self.port_edit.text().strip()

        if not ip:
            QMessageBox.warning(self, "错误", "请输入IP地址")
            return
        try:
            port = int(port_str) if port_str else 5866
        except ValueError:
            QMessageBox.warning(self, "错误", "端口号必须为数字")
            return

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("连接中...")
        self.status_light.setStyleSheet(f"background: {C['amber']}; border-radius: 7px;")
        self.status_label.setText("连接中...")
        self.status_label.setStyleSheet(f"color: {C['amber']};")
        self._log(f"正在连接 {ip}:{port} ...")

        def task():
            tcp_ok = self.tcp.connect(ip, port)
            # SSH 复用 TCP 的 IP + 硬编码凭证
            if self.mode == 1:  # 从手模式
                ssh_slave_ok = self.ssh.connect_slave(ip, SSH_USER, SSH_PASS)
                ssh_master_ok = False
            else:  # 主手模式
                ssh_slave_ok = False
                ssh_master_ok = self.ssh.connect_master(ip, SSH_USER, SSH_PASS)
            self.signal_connect_result.emit(tcp_ok, ssh_slave_ok, ssh_master_ok)

        threading.Thread(target=task, daemon=True).start()

    def _on_connect_result(self, tcp_ok: bool, ssh_slave_ok: bool, ssh_master_ok: bool):
        self.connect_btn.setEnabled(True)
        self.ssh_slave_connected = ssh_slave_ok
        self.ssh_master_connected = ssh_master_ok

        if tcp_ok:
            self.connected = True
            self.connect_btn.setText("🔌 断开")
            self.status_light.setStyleSheet(f"background: {C['green']}; border-radius: 7px;")
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet(f"color: {C['green']}; font-weight: bold;")
            self._update_ui_state()
            if self.mode == 1:
                ssh_text = "SSH从手✓" if ssh_slave_ok else "SSH从手✗"
            else:
                ssh_text = "SSH主手✓" if ssh_master_ok else "SSH主手✗"
            self._log(f"远程连接建立成功（{ssh_text}）")
            self._send_connect_init()
        else:
            self.connected = False
            self.connect_btn.setText("🔗 连接")
            self.status_light.setStyleSheet(f"background: {C['red']}; border-radius: 7px;")
            self.status_label.setText("TCP失败")
            self.status_label.setStyleSheet(f"color: {C['red']};")
            self._update_ui_state()
            self._log("TCP连接失败，SSH也不会可用")

    # ---------- 连接初始化 ----------
    def _send_connect_init(self):
        """根据主从模式发送初始化指令"""
        SLAVE_INIT = [
            "{Stop}",
            "{Start}",
            "{PushStatus||PushStatus||PushStatus --mode_id=0 --motion_cmd=1||PushStatus --mode_id=1 --motion_cmd=1||PushStatus --mode_id=2 --motion_cmd=1||PushStatus --mode_id=3 --motion_cmd=1||PushStatus --mode_id=4 --motion_cmd=1}",
        ]
        MASTER_INIT = [
            "{Stop}",
            "{Start}",
            "{Clear}",
            "{Mode}",
            "{SetMaxToq}",
            "{URecover}",
            "{Enable}",
            "{MtmSetPos}",
            "{MtmMoveP}",
        ]

        def task():
            cmds = SLAVE_INIT if self.mode == 1 else MASTER_INIT
            for i, cmd in enumerate(cmds, 1):
                self._log(f"初始化 [{i}/{len(cmds)}] 发送: {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0,expected=self.model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")
            self._log("初始化完成")
        threading.Thread(target=task, daemon=True).start()

    # ---------- 自动摆位（按下/松开） ----------
    def _set_pos_label(self, arm_id: int, text: str, busy: bool = False):
        """更新摆位按钮文字和样式"""
        btn = self.pos_btns[arm_id - 1]
        btn.setStyleSheet(self._pos_css(arm_id - 1, enabled=not busy, busy=busy))
        for child in btn.findChildren(QLabel):
            if "从臂" in child.text() or "执行" in child.text():
                child.setText(text)

    def _start_auto_position(self, arm_id: int):
        """按住 → 下发8条指令"""
        if not self.connected:
            QMessageBox.warning(self, "警告", "请先连接远程服务器")
            return

        with self.pos_lock:
            if self.pos_running[arm_id]:
                return
            self.pos_running[arm_id] = True

        self._set_pos_label(arm_id, f"从臂{arm_id}\n执行中...", busy=True)
        self._log(f"从臂{arm_id} 自动摆位 ▼ 按住")

        cmds = _build_press_cmds(arm_id)

        def task():
            for i, cmd in enumerate(cmds):
                with self.pos_lock:
                    if not self.pos_running[arm_id]:
                        self._log(f"从臂{arm_id} 序列已中断（第{i+1}条）")
                        return
                self._log(f"[{i+1}/8] 发送: {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0,expected=self.model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")

        threading.Thread(target=task, daemon=True).start()

    def _stop_auto_position(self, arm_id: int):
        """松开 → Stop → 100ms → Start → URecover"""
        with self.pos_lock:
            if not self.pos_running[arm_id]:
                return
            self.pos_running[arm_id] = False

        self._log(f"从臂{arm_id} 自动摆位 ▲ 松开")

        def task():
            release_cmds = _build_release_cmds()
            for cmd in release_cmds:
                self._log(f"[释放] 发送: {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0,expected=self.model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")

            self.signal_auto_pos_done.emit(arm_id)

        threading.Thread(target=task, daemon=True).start()

    def _on_auto_pos_done(self, arm_id: int):
        self._set_pos_label(arm_id, f"从臂{arm_id}\n自动摆位")
        self._log(f"从臂{arm_id} 自动摆位完成")

    # ---------- 路点管理 ----------
    def _load_trajectory_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择路点文件", os.path.dirname(os.path.abspath(__file__)),
            "路点文件 (*.txt);;所有文件 (*.*)"
        )
        if not file_path:
            return

        self.file_label.setText(os.path.basename(file_path))
        self.file_label.setStyleSheet(f"color: {C['slate']}; font-size: 8pt;")
        self._log(f"加载路点文件: {file_path}")

        def task():
            waypoints = self._parse_trajectory_file(file_path)
            self.signal_file_loaded.emit(waypoints)

        threading.Thread(target=task, daemon=True).start()

    @staticmethod
    def _parse_trajectory_file(file_path: str) -> List[Tuple[str, List[float]]]:
        waypoints = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                # 跳过表头行（包含 J1,J2 等列名）
                if i == 0 and ('J1' in line or 'name' in line.lower()):
                    continue
                # 按 Tab 切分
                parts = line.split('\t')
                if len(parts) < 2:
                    continue
                name = parts[0].rstrip(':')
                angles = []
                for val in parts[1:]:
                    try:
                        angles.append(float(val))
                    except ValueError:
                        break
                if angles:
                    waypoints.append((name, angles))
        except Exception as e:
            return [(f"错误: {e}", [])]
        return waypoints

    def _on_file_loaded(self, waypoints: List[Tuple[str, List[float]]]):
        self.table.setRowCount(0)
        self.waypoints = waypoints

        if not waypoints:
            self._log("警告: 文件中未解析到任何路点")
            self.wp_count_label.setText("共 0 个路点")
            return

        for name, angles in waypoints:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            angle_str = ", ".join([f"{a:.4f}" for a in angles])
            display = f"{angle_str}"
            item = QTableWidgetItem(display)
            item.setToolTip(angle_str)
            self.table.setItem(row, 1, item)

        self.wp_count_label.setText(f"共 {len(waypoints)} 个路点")
        self._log(f"成功加载 {len(waypoints)} 个路点")
        self._update_exec_btn()
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _get_selected_arm(self) -> int:
        return self.selected_arm

    def _get_selected_hand(self) -> int:
        return self.selected_hand

    def _execute_waypoint(self):
        if not self.connected:
            QMessageBox.warning(self, "警告", "请先连接远程服务器")
            return

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在路点列表中选中一个路点")
            return

        wp_name = self.table.item(row, 0).text()
        angles = []
        for name, ang in self.waypoints:
            if name == wp_name:
                angles = ang
                break

        angle_str = ", ".join([f"{a:.4f}" for a in angles])
        self._log(f"执行路点: {wp_name} 角度: [{angle_str}]")
        self.exec_btn.setEnabled(False)
        self.exec_btn.setText("执行中...")

        def task():
            if self.mode == 0:
                hand = self._get_selected_hand()
                cmd = _build_master_exec_cmd(angles, hand)
                self._log(f"执行 ({'左手' if hand==0 else '右手'}): {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0,expected=self.model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")
            else:
                arm_id = self._get_selected_arm()
                cmds = _build_slave_exec_cmds(arm_id, angles)
                for i, cmd in enumerate(cmds, 1):
                    self._log(f"[{i}/7] 发送: {cmd}")
                    resp, err = self.tcp.send_and_recv(cmd, timeout=500.0 ,expected=self.model)
                    if resp:
                        for line in resp.split("\n"):
                            self._log(f"  <- {line}")
                    if err:
                        self._log(f"  -> {err}")

            # 所有返回已收到 → 直接保存关节角数据（同一线程）
            
            self._do_save_after_exec(wp_name)
            self.signal_exec_done.emit()

        threading.Thread(target=task, daemon=True).start()

    # ---------- 路点执行完成回调 ----------
    def _on_exec_done(self):
        self.exec_btn.setText("▶执行路点")
        self._update_exec_btn()
        self._log("路点执行完成")

    # ---------- 数据存储 ----------
    def _get_data_dir(self) -> str:
        """获取数据存储目录"""
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def _write_joint_file(self, filepath: str, angle_vals: list, num_joints: int, prefix: str) -> int:
        """将关节角数据写入.cst文件（同JointMonitor格式）
        返回写入的行号（从1开始），失败返回-1"""
        if filepath not in self.file_locks:
            self.file_locks[filepath] = threading.Lock()

        with self.file_locks[filepath]:
            try:
                file_exists = os.path.exists(filepath)
                need_header = not file_exists or os.path.getsize(filepath) == 0

                current_lines = 0
                if file_exists and not need_header:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        current_lines = len(f.readlines()) - 1  # 减去表头
                new_line_no = current_lines + 1

                with open(filepath, 'a', encoding='utf-8') as f:
                    if need_header:
                        header_cols = ["name"] + [f"J{i+1}" for i in range(num_joints)]
                        f.write(" ".join(header_cols) + "\n")
                        self._log(f"创建文件并写入表头: {os.path.basename(filepath)}")
                        new_line_no = 1

                    values_str = " ".join([f"{v:.6f}" for v in angle_vals])
                    f.write(f"{prefix}: {values_str}\n")

                self._log(f"数据已追加到 {os.path.basename(filepath)} (第{new_line_no}个点)")
                return new_line_no
            except Exception as e:
                self._log(f"写入文件失败 {filepath}: {e}")
                return -1

    def _do_save_after_exec(self, wp_name: str):
        """执行线程中直接调用：收到所有返回后，立即 SSH 读取实际角度并保存"""
        waypoint_angles = next((ang for n, ang in self.waypoints if n == wp_name), None)
        if not waypoint_angles:
            return

        actual_angles = None
        source = "waypoint"

        try:
            if self.mode == 1 and self.ssh_slave_connected:
                arm_id = self._get_selected_arm()
                ssh_angles = self.ssh.read_slave(arm_id)
                if ssh_angles:
                    actual_angles = ssh_angles
                    source = "SSH"

            elif self.mode == 0 and self.ssh_master_connected:
                hand = self._get_selected_hand()
                arm_name = "Left" if hand == 0 else "Right"
                ssh_angles, view_angle = self.ssh.read_master(arm_name)
                if ssh_angles:
                    actual_angles = ssh_angles
                    source = "SSH"
                    if view_angle is not None:
                        self._save_view_angle_to_file(view_angle)

            if actual_angles is None:
                actual_angles = waypoint_angles

            if self.mode == 1:
                arm_id = self._get_selected_arm()
                front_8 = actual_angles[:8]
                back_4 = actual_angles[8:12] if len(actual_angles) >= 12 else []
                psm_file = os.path.join(self.data_dir, f"psm{arm_id}_joint.cst")
                inst_file = os.path.join(self.data_dir, f"inst{arm_id}_joint.cst")
                self._write_joint_file(psm_file, front_8, 8, "actpos")
                if back_4:
                    self._write_joint_file(inst_file, back_4, 4, "actpos")
            elif self.mode == 0:
                hand = self._get_selected_hand()
                filename = "mtm1_joint.cst" if hand == 0 else "mtm2_joint.cst"
                filepath = os.path.join(self.data_dir, filename)
                self._write_joint_file(filepath, actual_angles, 7, "addlpos")

            self._log(f"路点 [{wp_name}] 数据已保存 [{source}]")
        except Exception as e:
            self._log(f"执行后保存关节角失败: {e}")

    def _save_after_waypoint(self, auto: bool = False):
        """保存关节角数据到.cst文件
        - SSH可用时：读取远程日志实际关节角再保存（同 JointMonitor）
        - SSH不可用时：回退到保存路点目标角度"""
        row = self.table.currentRow()
        if row < 0:
            if not auto:
                QMessageBox.information(self, "提示", "请先在路点列表中选中一个路点")
            return

        wp_name = self.table.item(row, 0).text()

        # 获取路点数据作为 fallback
        waypoint_angles = None
        for name, ang in self.waypoints:
            if name == wp_name:
                waypoint_angles = ang
                break
        if not waypoint_angles:
            self._log("无法保存：未找到路点数据")
            return

        def task():
            try:
                actual_angles = None
                source = "waypoint"

                if self.mode == 1 and self.ssh_slave_connected:
                    arm_id = self._get_selected_arm()
                    ssh_angles = self.ssh.read_slave(arm_id)
                    if ssh_angles:
                        actual_angles = ssh_angles
                        source = "SSH"
                        self._log(f"从臂{arm_id} SSH读取实机关节角成功")
                    else:
                        self._log(f"从臂{arm_id} SSH读取失败")

                elif self.mode == 0 and self.ssh_master_connected:
                    hand = self._get_selected_hand()
                    arm_name = "Left" if hand == 0 else "Right"
                    ssh_angles, view_angle = self.ssh.read_master(arm_name)
                    if ssh_angles:
                        actual_angles = ssh_angles
                        source = "SSH"
                        self._log(f"主手{arm_name} SSH读取实机关节角成功")
                        if view_angle is not None:
                            self._save_view_angle_to_file(view_angle)
                    else:
                        self._log(f"主手{arm_name} SSH读取失败")

                # Fallback: 使用路点目标角度
                if actual_angles is None:
                    if self.ssh_slave_connected or self.ssh_master_connected:
                        self._log("SSH读取失败，回退到路点目标角度")
                    actual_angles = waypoint_angles

                # 保存角度到 .cst 文件
                if self.mode == 1:
                    arm_id = self._get_selected_arm()
                    front_8 = actual_angles[:8]
                    back_4 = actual_angles[8:12] if len(actual_angles) >= 12 else []
                    psm_file = os.path.join(self.data_dir, f"psm{arm_id}_joint.cst")
                    inst_file = os.path.join(self.data_dir, f"inst{arm_id}_joint.cst")

                    line_no_psm = self._write_joint_file(psm_file, front_8, 8, "actpos")
                    if back_4:
                        line_no_inst = self._write_joint_file(inst_file, back_4, 4, "actpos")
                        if line_no_inst > 0:
                            self._log(f"从臂{arm_id} 后4关节保存完成 (第{line_no_inst}个点)")
                    else:
                        self._log(f"从臂{arm_id} 无后4关节数据，跳过")

                    if line_no_psm > 0:
                        self._log(f"从臂{arm_id} 前8关节保存完成 (第{line_no_psm}个点) [{source}]")

                elif self.mode == 0:
                    hand = self._get_selected_hand()
                    filename = "mtm1_joint.cst" if hand == 0 else "mtm2_joint.cst"
                    filepath = os.path.join(self.data_dir, filename)
                    line_no = self._write_joint_file(filepath, actual_angles, 7, "addlpos")
                    if line_no > 0:
                        self._log(f"{'左手' if hand==0 else '右手'} 关节数据保存完成 (第{line_no}个点) [{source}]")

                if auto:
                    self._log(f"路点 [{wp_name}] 数据已保存 [{source}]")
            except Exception as e:
                self._log(f"保存数据失败: {e}")

        threading.Thread(target=task, daemon=True).start()

    def _save_view_angle_to_file(self, view_angle: float):
        """保存 view_angle 到文件（同 JointMonitor）"""
        if view_angle is None:
            return
        filepath = os.path.join(self.data_dir, "view_angle.cst")
        self._write_joint_file(filepath, [view_angle], 1, "view_angle")

    # ---------- 急停 ----------
    def _emergency_stop(self):
        """急停: Stop → 0.5s → Start"""
        if not self.connected:
            return
        self._log("🛑急停触发")
        

        def task():
            for cmd in ["{Stop}", "{Start}"]:
                self._log(f"急停 发送: {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0, expected=self.model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")
            self._log("急停完成")

        threading.Thread(target=task, daemon=True).start()

    # ---------- 退出 ----------
    def closeEvent(self, event):
        if self.connected:
            self.tcp.disconnect()
        if self.ssh_slave_connected or self.ssh_master_connected:
            self.ssh.disconnect_all()
        super().closeEvent(event)


# ==================== 入口 ====================
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AutoKinematicsWindow()
    window.show()
    sys.exit(app.exec_())
