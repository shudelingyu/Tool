#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运动学自动辨识工具 (PyQt5版)
- SSH远程连接到远端
- 自动摆位控制（从臂1-4）
- 读取identifytrajectory路点文件（cvt/cst/csv/txt）并执行
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
    QPlainTextEdit, QFileDialog, QMessageBox, QMenu,
    QStackedWidget, QSizePolicy, QDoubleSpinBox, QAbstractSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon, QCursor


# ==================== 配色方案 ====================
C = {
    "indigo":    "#4F46E5",
    "indigo_dk": "#3730A3",
    "indigo_lt": "#818CF8",
    "indigo_md": "#6366F1",
    "indigo_soft": "#EEF2FF",
    "slate":     "#1E293B",
    "slate_md":  "#475569",
    "slate_lt":  "#94A3B8",
    "bg":        "#F1F5F9",
    "card":      "#FFFFFF",
    "green":     "#10B981",
    "green_dk":  "#059669",
    "red":       "#EF4444",
    "red_dk":    "#DC2626",
    "amber":     "#F59E0B",
    "border":    "#E2E8F0",
    "border_strong": "#CBD5E1",
    "console":   "#0B1220",
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
    "MoveAbsolute --num={num} --pos={{{wp}}} --vel={{{vel}}} --acc={{{acc}}} --jerk={{{jerk}}}",
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

def _resource_path(name: str) -> str:
    """资源路径：源码运行时取脚本目录，PyInstaller 打包后取解包目录"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


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


def _build_slave_exec_cmds(arm_id: int, angles: List[float],
                           vel: float = 0.15, acc: float = 0.30, jerk: float = 0.30) -> List[str]:
    """构建从手执行路点的7条指令，angles为关节角度列表，vel/acc/jerk为运动参数"""
    num = ARM_CFG[arm_id]["num"]
    angle_str = ",".join(f"{a:.4f}" for a in angles)
    params = {
        "num": num,
        "wp": angle_str,
        "vel": f"{vel:.2f}",
        "acc": f"{acc:.2f}",
        "jerk": f"{jerk:.2f}",
    }
    cmds = []
    for template in SLAVE_EXEC_TEMPLATE:
        cmd = template.format(**params)
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
/* ── 全局 ── */
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 9.5pt;
    color: {C['slate']};
}}
QToolTip {{
    background: {C['slate']}; color: #F8FAFC;
    border: none; padding: 6px 8px; font-size: 8.5pt;
}}

/* ── 标题栏 ── */
#headerBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C['indigo']}, stop:0.55 {C['indigo_md']}, stop:1 {C['indigo_dk']});
    min-height: 64px; max-height: 64px; border: none;
}}
#brandTitle {{
    color: #FFFFFF; font-size: 14pt; font-weight: 600; letter-spacing: 1px;
}}
#brandChip {{
    background: rgba(255, 255, 255, 0.12); color: #DDD6FE;
    border-radius: 7px; padding: 2px 9px;
    font-size: 7.5pt; font-weight: 600; letter-spacing: 1px;
}}
#brandLogo {{
    background: #FFFFFF; border-radius: 9px;
}}
#headerMeta {{ color: #C7D2FE; font-size: 8.5pt; }}

/* ── 卡片 ── */
Card {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
#cardAccent {{
    background: {C['indigo']}; border-radius: 2px;
    min-width: 4px; max-width: 4px; min-height: 15px; max-height: 15px;
}}
#cardTitle {{
    font-size: 10.5pt; font-weight: 600; color: {C['slate']};
}}
#fieldLabel {{ color: #64748B; font-size: 8.5pt; }}
#hintLabel {{ color: {C['slate_lt']}; font-size: 8pt; }}

/* ── 路点拖拽区 ── */
#dropZone {{
    background: #F8FAFC;
    border: 1.5px dashed {C['border_strong']};
    border-radius: 10px;
}}
#dropZone[state="hover"] {{
    background: {C['indigo_soft']};
    border: 1.5px dashed {C['indigo']};
}}
#dropZone[state="loaded"] {{
    background: #FFFFFF;
    border: 1px solid {C['border']};
}}
#dropZone[state="error"] {{
    background: #FEF2F2;
    border: 1.5px dashed #F87171;
}}
#dropZone[state="loading"] {{
    background: {C['indigo_soft']};
    border: 1.5px solid {C['indigo_md']};
}}
#dropIcon {{ font-size: 20px; color: {C['indigo_lt']}; background: transparent; }}
#dropTitle {{ font-size: 9.5pt; font-weight: 600; color: {C['slate_md']}; background: transparent; }}
#dropHint {{ font-size: 8pt; color: {C['slate_lt']}; background: transparent; }}
#dropBadge {{
    background: {C['indigo_soft']}; color: {C['indigo']};
    border-radius: 9px; padding: 3px 10px;
    font-size: 8pt; font-weight: 600;
}}

/* ── 目标选择菜单 ── */
QMenu {{
    background: #FFFFFF;
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 6px;
    color: {C['slate']};
}}
QMenu::item:selected {{
    background: {C['indigo_soft']};
    color: {C['indigo']};
}}
QMenu::separator {{
    height: 1px; background: {C['border']}; margin: 4px 8px;
}}

/* ── 输入框 ── */
QLineEdit {{
    border: 1.5px solid {C['border_strong']};
    border-radius: 8px;
    padding: 0 10px;
    min-height: 30px; max-height: 30px;
    background: {C['card']}; color: {C['slate']};
    selection-background-color: {C['indigo_lt']};
    font-size: 9.5pt;
}}
QLineEdit:hover {{ border-color: {C['slate_lt']}; }}
QLineEdit:focus {{ border: 1.5px solid {C['indigo']}; background: #FFFFFF; }}

QDoubleSpinBox {{
    border: 1.5px solid {C['border_strong']};
    border-radius: 8px;
    padding: 0 8px;
    min-height: 28px; max-height: 28px;
    background: {C['card']}; color: {C['slate']};
    selection-background-color: {C['indigo_lt']};
    font-size: 9pt;
}}
QDoubleSpinBox:hover {{ border-color: {C['slate_lt']}; }}
QDoubleSpinBox:focus {{ border: 1.5px solid {C['indigo']}; background: #FFFFFF; }}
QDoubleSpinBox:disabled {{ background: #F8FAFC; color: {C['slate_lt']}; border-color: {C['border']}; }}

/* ── 按钮通用 ── */
QPushButton {{
    border: none; border-radius: 8px;
    padding: 0 16px;
    font-weight: 600; font-size: 9pt;
}}
QPushButton:disabled {{ background: #E2E8F0; color: {C['slate_lt']}; }}

#primaryBtn {{ background: {C['indigo']}; color: #FFFFFF; padding: 0 22px; min-height: 32px; }}
#primaryBtn:hover {{ background: {C['indigo_dk']}; }}
#primaryBtn:pressed {{ background: #312E81; }}
#primaryBtn:disabled {{ background: #C7D2FE; color: #EEF2FF; }}

#secondaryBtn {{
    background: {C['card']}; color: {C['slate_md']};
    border: 1px solid {C['border_strong']}; padding: 0 16px; min-height: 32px;
}}
#secondaryBtn:hover {{ background: #F8FAFC; border-color: {C['slate_lt']}; color: {C['slate']}; }}
#secondaryBtn:pressed {{ background: #F1F5F9; }}
#secondaryBtn:disabled {{ background: #F8FAFC; color: {C['slate_lt']}; border-color: {C['border']}; }}

#ghostBtn {{
    background: transparent; color: {C['slate_md']};
    border: none; padding: 0 10px; font-size: 8.5pt; font-weight: 500;
    min-height: 24px; max-height: 24px;
}}
#ghostBtn:hover {{ background: #F1F5F9; color: {C['slate']}; }}
#ghostBtn:disabled {{ background: transparent; color: {C['slate_lt']}; }}

#dangerBtn {{ background: {C['red']}; color: #FFFFFF; padding: 0 24px; min-height: 34px; }}
#dangerBtn:hover {{ background: {C['red_dk']}; }}
#dangerBtn:pressed {{ background: #B91C1C; }}
#dangerBtn:disabled {{ background: #FECACA; color: #FEF2F2; }}

#execBtn {{ background: {C['green']}; color: #FFFFFF; padding: 0 26px; min-height: 34px; }}
#execBtn:hover {{ background: {C['green_dk']}; }}
#execBtn:pressed {{ background: #047857; }}
#execBtn:disabled {{ background: #D1FAE5; color: #ECFDF5; }}

/* ── 分段选择（模式 / 执行目标） ── */
#segBtn {{
    background: {C['card']}; color: {C['slate_md']};
    border: 1px solid {C['border_strong']}; border-radius: 7px;
    min-height: 26px; max-height: 26px; padding: 0 12px;
    font-size: 8.5pt; font-weight: 500;
}}
#segBtn:hover {{ background: #F8FAFC; border-color: {C['slate_lt']}; }}
#segBtn:checked {{
    background: {C['indigo']}; color: #FFFFFF; border-color: {C['indigo']};
    font-weight: 600;
}}
#segBtn:checked:hover {{ background: {C['indigo_dk']}; border-color: {C['indigo_dk']}; }}
#segBtn:disabled {{ background: #F8FAFC; color: {C['slate_lt']}; border-color: {C['border']}; }}

/* ── 状态胶囊 ── */
#statusPill {{ background: #F1F5F9; border-radius: 13px; min-height: 26px; max-height: 26px; }}
#statusPill[state="ok"] {{ background: #ECFDF5; }}
#statusPill[state="warn"] {{ background: #FFFBEB; }}
#statusPill[state="err"] {{ background: #FEF2F2; }}
#statusDot {{
    border-radius: 4px; background: {C['slate_lt']};
    min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;
}}
#statusPill[state="warn"] #statusDot {{ background: {C['amber']}; }}
#statusPill[state="ok"] #statusDot {{ background: {C['green']}; }}
#statusPill[state="err"] #statusDot {{ background: {C['red']}; }}
#statusLabel {{ font-size: 8.5pt; color: #64748B; background: transparent; }}
#statusPill[state="warn"] #statusLabel {{ color: #B45309; font-weight: 600; }}
#statusPill[state="ok"] #statusLabel {{ color: #047857; font-weight: 600; }}
#statusPill[state="err"] #statusLabel {{ color: #B91C1C; font-weight: 600; }}

/* ── 摆位按钮内文字 ── */
#posIcon {{ color: #FFFFFF; font-size: 20px; background: transparent; }}
#posText {{ color: #FFFFFF; font-size: 11pt; font-weight: 600; background: transparent; }}
#posHint {{ color: rgba(255, 255, 255, 0.75); font-size: 8pt; background: transparent; }}

/* ── 表格 ── */
QTableWidget {{
    border: 1px solid {C['border']}; border-radius: 8px;
    background: {C['card']};
    alternate-background-color: #FAFBFC;
    gridline-color: transparent;
    selection-background-color: {C['indigo_soft']};
    selection-color: {C['slate']};
    font-size: 9pt;
    outline: none;
}}
QTableWidget::item {{ padding: 4px 10px; border: none; }}
QTableWidget::item:selected {{ background: {C['indigo_soft']}; color: {C['indigo_dk']}; }}
QHeaderView::section {{
    background: #F8FAFC; color: #64748B;
    font-weight: 600; font-size: 8.5pt;
    border: none; border-bottom: 1px solid {C['border']};
    padding: 6px 10px;
}}
QTableCornerButton::section {{ background: #F8FAFC; border: none; }}

/* ── 计数徽标 ── */
#countBadge {{
    background: #F1F5F9; color: {C['slate_md']};
    border-radius: 10px; padding: 3px 10px; font-size: 8.5pt;
}}

/* ── 空状态 ── */
#emptyState {{ background: #FAFBFC; border: 1px dashed {C['border_strong']}; border-radius: 8px; }}
#emptyTitle {{ color: {C['slate_md']}; font-size: 9.5pt; font-weight: 600; }}
#emptyHint {{ color: {C['slate_lt']}; font-size: 8.5pt; }}

/* ── 日志控制台 ── */
#logEdit {{
    background: {C['console']}; color: #E2E8F0;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 9pt;
    border: none; border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {C['indigo_md']};
}}
#logEdit QScrollBar::handle:vertical {{ background: #334155; }}
#logEdit QScrollBar::handle:vertical:hover {{ background: #475569; }}

/* ── 滚动条 ── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {C['slate_lt']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CBD5E1; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
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


# ==================== 路点拖拽区 ====================
class WaypointDropZone(QFrame):
    """路点文件拖拽区：拖入 cvt/cst/csv/txt，点击可浏览选择"""

    file_dropped = pyqtSignal(str)
    browse_requested = pyqtSignal()

    SUFFIXES = (".cvt", ".cst", ".csv", ".txt")
    STATE_COLORS = {
        "idle":    ("#818CF8", "#475569", "#94A3B8"),
        "hover":   ("#4F46E5", "#3730A3", "#6366F1"),
        "loaded":  ("#6366F1", "#1E293B", "#94A3B8"),
        "loading": ("#4F46E5", "#3730A3", "#6366F1"),
        "error":   ("#EF4444", "#B91C1C", "#DC2626"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("state", "idle")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(62)
        self.setToolTip("拖入路点文件，随后选择所属从臂/手；点击也可选择文件")
        self._has_file = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 12, 8)
        layout.setSpacing(10)

        self.icon = QLabel("📥")
        self.icon.setObjectName("dropIcon")
        self.icon.setFixedWidth(24)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.title = QLabel("拖入路点文件")
        self.title.setObjectName("dropTitle")
        self.title.setMinimumHeight(24)
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hint = QLabel("支持 .cvt / .cst / .csv / .txt · 拖入后选择目标")
        self.hint.setObjectName("dropHint")
        self.hint.setMinimumHeight(18)
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_col.addWidget(self.title)
        text_col.addWidget(self.hint)
        layout.addLayout(text_col, 1)

        self.target_badge = QLabel("未选择")
        self.target_badge.setObjectName("dropBadge")
        self.target_badge.setAlignment(Qt.AlignCenter)
        self.target_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.target_badge)

        self.browse_btn = QPushButton("选择文件")
        self.browse_btn.setObjectName("ghostBtn")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setToolTip("浏览并选择路点文件")
        self.browse_btn.clicked.connect(self.browse_requested)
        layout.addWidget(self.browse_btn)

        self._apply_state()

    # ---------- 对外接口 ----------
    def set_target(self, text: str):
        self.target_badge.setText(text)

    def set_file(self, filename: str = "", count: int = 0):
        self._has_file = bool(filename)
        if filename:
            self.title.setText(filename)
            self.hint.setText(f"{count} 个路点 · 拖入新文件可替换")
            self.icon.setText("📄")
            self._set_state("loaded")
        else:
            self.title.setText("拖入路点文件")
            self.hint.setText("支持 .cvt / .cst / .csv / .txt · 拖入后选择目标")
            self.icon.setText("📥")
            self._set_state("idle")

    def set_loading(self, filename: str):
        self.title.setText(filename)
        self.hint.setText("正在解析路点…")
        self.icon.setText("⏳")
        self._set_state("loading")

    def set_error(self, message: str = "文件解析失败"):
        self.title.setText(message)
        self.hint.setText("请检查文件格式，或拖入其他文件")
        self.icon.setText("⚠")
        self._set_state("error")

    # ---------- 拖拽 ----------
    @classmethod
    def _pick_file(cls, mime) -> Optional[str]:
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            path = url.toLocalFile()
            if path and os.path.isfile(path) and path.lower().endswith(cls.SUFFIXES):
                return path
        return None

    def dragEnterEvent(self, event):
        if self._pick_file(event.mimeData()):
            event.acceptProposedAction()
            self._set_state("hover")
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._pick_file(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_state("loaded" if self._has_file else "idle")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        path = self._pick_file(event.mimeData())
        if not path:
            event.ignore()
            return
        event.acceptProposedAction()
        self._set_state("loaded" if self._has_file else "idle")
        self.file_dropped.emit(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.browse_requested.emit()
        super().mousePressEvent(event)

    # ---------- 状态 ----------
    def _set_state(self, state: str):
        if self.property("state") != state:
            self.setProperty("state", state)
        self._apply_state()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _apply_state(self):
        """显式设置子控件颜色，避免属性选择器不刷新后代样式"""
        state = self.property("state")
        icon_color, title_color, hint_color = self.STATE_COLORS.get(state, self.STATE_COLORS["idle"])
        self.icon.setStyleSheet(f"font-size: 20px; color: {icon_color}; background: transparent;")
        self.title.setStyleSheet(
            f"font-size: 9.5pt; font-weight: 600; color: {title_color}; background: transparent;")
        self.hint.setStyleSheet(f"font-size: 8pt; color: {hint_color}; background: transparent;")


# ==================== 卡片组件 ====================
class Card(QFrame):
    """卡片容器 — 标题左侧带强调条，可选右上角操作控件"""

    def __init__(self, title: str = "", parent=None, action: QWidget = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(12)

        if title:
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(8)

            accent = QFrame()
            accent.setObjectName("cardAccent")
            accent.setFixedSize(4, 15)
            title_row.addWidget(accent)

            title_lbl = QLabel(title)
            title_lbl.setObjectName("cardTitle")
            title_row.addWidget(title_lbl)
            title_row.addStretch(1)

            if action is not None:
                title_row.addWidget(action)

            self._layout.addLayout(title_row)

        self._content = QVBoxLayout()
        self._content.setSpacing(10)
        self._layout.addLayout(self._content, 1)

    def addLayout(self, layout):
        self._content.addLayout(layout)

    def addWidget(self, widget, stretch: int = 0):
        self._content.addWidget(widget, stretch)


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
    signal_file_loaded = pyqtSignal(object)
    signal_exec_done = pyqtSignal()
    signal_log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("运动学自动辨识工具")
        self.setWindowIcon(QIcon(_resource_path("app_icon.ico")))
        self._center()

        # TCP
        self.tcp = TcpClient(log_callback=self._log)
        self.connected = False

        # SSH
        self.ssh = SSHReader(log_callback=self._log)
        self.ssh_slave_connected = False
        self.ssh_master_connected = False

        # 单目标路点：一次只保留一个文件及其归属
        self.waypoints: List[Tuple[str, List[float]]] = []
        self.current_target: Optional[Tuple[str, int]] = None
        self.loaded_filename = ""
        self.loaded_file_path = ""
        self.executed_names: set = set()
        self._load_seq = 0

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
        """按可用屏幕区域自适应尺寸并居中，避免小屏被裁切"""
        avail = QApplication.primaryScreen().availableGeometry()
        w = max(900, min(1040, avail.width() - 60))
        h = max(620, min(860, avail.height() - 80))
        self.setMinimumSize(min(940, w), min(700, h))
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2,
                  avail.y() + (avail.height() - h) // 2)

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
        hdr.setSpacing(12)

        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(QIcon(_resource_path("app_icon.ico")).pixmap(26, 26))
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignCenter)
        hdr.addWidget(logo)

        title = QLabel("运动学自动辨识工具")
        title.setObjectName("brandTitle")
        hdr.addWidget(title)

        chip = QLabel("KINEMATICS ID")
        chip.setObjectName("brandChip")
        hdr.addWidget(chip)

        hdr.addStretch()

        subtitle = QLabel(f"TCP / SSH   ·   {datetime.now().strftime('%Y-%m-%d')}")
        subtitle.setObjectName("headerMeta")
        hdr.addWidget(subtitle)

        root.addWidget(header)

        # ========== 主体 ==========
        body = QVBoxLayout()
        body.setContentsMargins(20, 18, 20, 18)
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
        self.clear_log_btn = QPushButton("清空")
        self.clear_log_btn.setObjectName("ghostBtn")
        self.clear_log_btn.setToolTip("清空运行日志")
        self.clear_log_btn.setCursor(Qt.PointingHandCursor)
        self.clear_log_btn.setFixedHeight(24)
        self.clear_log_btn.clicked.connect(lambda: self.log_edit.clear())

        log_card = Card("📝 运行日志", action=self.clear_log_btn)
        log_card.setMaximumHeight(168)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("logEdit")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(1000)
        log_card.addWidget(self.log_edit, 1)
        body.addWidget(log_card)

        root.addLayout(body)

        # 默认值已在输入框构造时设置

    # ---------- 连接卡片 ----------
    def _build_connect_card(self):
        card = Card("🔗 远程连接")

        row = QHBoxLayout()
        row.setSpacing(12)

        self.ip_edit = QLineEdit("192.168.11.11")
        self.ip_edit.setFixedWidth(142)
        self.ip_edit.setFont(QFont("Consolas", 9))
        self.ip_edit.setPlaceholderText("远端 IP")
        self.ip_edit.setToolTip("远端控制器 IP 地址，回车可直接连接")
        self.ip_edit.returnPressed.connect(self._do_connect)
        row.addWidget(self._labeled_widget("主机 IP", self.ip_edit))

        self.port_edit = QLineEdit("7866")
        self.port_edit.setFixedWidth(74)
        self.port_edit.setFont(QFont("Consolas", 9))
        self.port_edit.setPlaceholderText("端口")
        self.port_edit.setToolTip("TCP 端口，回车可直接连接")
        self.port_edit.returnPressed.connect(self._do_connect)
        row.addWidget(self._labeled_widget("端口", self.port_edit))

        self.connect_btn = QPushButton("🔗 连接")
        self.connect_btn.setObjectName("primaryBtn")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.setToolTip("建立 TCP 与 SSH 连接")
        self.connect_btn.clicked.connect(self._do_connect)
        row.addWidget(self.connect_btn)

        # ── 连接状态胶囊 ──
        self.status_pill = QFrame()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("state", "idle")
        pill = QHBoxLayout(self.status_pill)
        pill.setContentsMargins(11, 0, 13, 0)
        pill.setSpacing(7)

        self.status_dot = QFrame()
        self.status_dot.setObjectName("statusDot")
        pill.addWidget(self.status_dot)

        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("statusLabel")
        pill.addWidget(self.status_label)
        row.addWidget(self.status_pill)

        row.addStretch()

        # ── 主手/从手切换 ──
        mode_label = QLabel("模式")
        mode_label.setObjectName("fieldLabel")
        row.addWidget(mode_label)

        self.mode_btn_master = QPushButton("主手")
        self.mode_btn_master.setObjectName("segBtn")
        self.mode_btn_master.setCheckable(True)
        self.mode_btn_master.setCursor(Qt.PointingHandCursor)
        self.mode_btn_master.setToolTip("主手模式：执行 MtmMoveP 指令")
        self.mode_btn_master.clicked.connect(lambda: self._set_mode(0))

        self.mode_btn_slave = QPushButton("从手")
        self.mode_btn_slave.setObjectName("segBtn")
        self.mode_btn_slave.setCheckable(True)
        self.mode_btn_slave.setCursor(Qt.PointingHandCursor)
        self.mode_btn_slave.setToolTip("从手模式：执行 MoveAbsolute 指令")
        self.mode_btn_slave.clicked.connect(lambda: self._set_mode(1))
        self.mode_btn_slave.setChecked(True)
        self._style_mode_buttons()

        row.addWidget(self.mode_btn_master)
        row.addWidget(self.mode_btn_slave)

        card.addLayout(row)

        return card

    @staticmethod
    def _labeled_widget(label: str, widget: QWidget) -> QWidget:
        """带标签的输入框"""
        container = QFrame()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        lbl = QLabel(label)
        lbl.setObjectName("fieldLabel")
        layout.addWidget(lbl)
        layout.addWidget(widget)
        return container

    @staticmethod
    def _make_param_spin(value: float, step: float, tooltip: str) -> QDoubleSpinBox:
        """执行参数输入框（无箭头、两位小数）"""
        spin = QDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(0.01, 10.00)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setFixedWidth(72)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setKeyboardTracking(False)
        spin.setToolTip(tooltip)
        return spin

    # ---------- 摆位卡片 ----------
    def _build_pos_card(self):
        card = Card("🎯 自动摆位")
        grid = QGridLayout()
        grid.setSpacing(12)

        self.pos_btns = []
        for i in range(4):
            ac = ARM_COLORS[i]
            btn = PosButton(i + 1)
            btn.setMinimumSize(0, 116)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"按住执行从臂{i + 1}自动摆位，松开即释放")
            btn.setEnabled(False)
            btn.press_arm.connect(self._start_auto_position)
            btn.release_arm.connect(self._stop_auto_position)

            # 按钮内用垂直布局排列图标+文字
            bl = QVBoxLayout()
            bl.setContentsMargins(8, 10, 8, 10)
            bl.setSpacing(3)
            bl.addStretch()

            icon = QLabel(ac["icon"])
            icon.setObjectName("posIcon")
            icon.setAlignment(Qt.AlignCenter)
            icon.setAttribute(Qt.WA_TransparentForMouseEvents)
            bl.addWidget(icon)

            txt = QLabel(f"从臂 {i+1}")
            txt.setObjectName("posText")
            txt.setAlignment(Qt.AlignCenter)
            txt.setAttribute(Qt.WA_TransparentForMouseEvents)
            bl.addWidget(txt)

            hint = QLabel("请先连接")
            hint.setObjectName("posHint")
            hint.setAlignment(Qt.AlignCenter)
            hint.setAttribute(Qt.WA_TransparentForMouseEvents)
            bl.addWidget(hint)

            bl.addStretch()
            btn.setLayout(bl)

            row, col = i // 2, i % 2
            grid.addWidget(btn, row, col)
            self.pos_btns.append(btn)

        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        # 初始为未连接状态
        for i in range(4):
            self._apply_pos_state(i, enabled=False)

        card.addLayout(grid)
        return card

    def _pos_css(self, idx: int, enabled: bool = True, busy: bool = False) -> str:
        ac = ARM_COLORS[idx]
        if busy:
            bg = hov = pr = "#94A3B8"
        elif not enabled:
            bg = hov = pr = "#E2E8F0"
        else:
            bg, hov, pr = ac["bg"], ac["hover"], ac["hover"]
        return (
            f"QPushButton {{ background: {bg}; border: none; border-radius: 12px; padding: 0; "
            f"min-height: 116px; }}"
            f"QPushButton:hover {{ background: {hov}; }}"
            f"QPushButton:pressed {{ background: {pr}; }}"
            f"QPushButton:disabled {{ background: #E2E8F0; }}"
        )

    def _apply_pos_state(self, idx: int, enabled: bool, busy: bool = False):
        """统一下发摆位按钮的外观状态（按钮底色 + 内部文字颜色）"""
        btn = self.pos_btns[idx]
        btn.setStyleSheet(self._pos_css(idx, enabled=enabled, busy=busy))

        main_color = "#FFFFFF" if (enabled or busy) else "#94A3B8"
        if busy:
            hint_color, hint_text = "#E2E8F0", "正在执行 · 松开停止"
        elif enabled:
            hint_color, hint_text = "#E0E7FF", "自动摆位 · 按住"
        else:
            hint_color, hint_text = "#94A3B8", "请先连接"

        for child in btn.findChildren(QLabel):
            name = child.objectName()
            if name == "posIcon":
                child.setStyleSheet(f"font-size: 20px; color: {main_color}; background: transparent;")
            elif name == "posText":
                child.setStyleSheet(
                    f"font-size: 11pt; font-weight: 600; color: {main_color}; background: transparent;")
            elif name == "posHint":
                child.setText(hint_text)
                child.setStyleSheet(f"font-size: 8pt; color: {hint_color}; background: transparent;")

    # ---------- 路点卡片 ----------
    def _build_waypoint_card(self):
        card = Card("📋 路点管理")

        # 文件拖拽区（拖入/选择文件后再指定归属）
        self.drop_zone = WaypointDropZone()
        self.drop_zone.file_dropped.connect(self._on_file_dropped)
        self.drop_zone.browse_requested.connect(lambda: self._load_trajectory_file())
        self.drop_zone.set_target("未选择")
        card.addWidget(self.drop_zone)

        # 执行参数（MoveAbsolute，仅从手生效）
        self.param_frame = QFrame()
        param_row = QHBoxLayout(self.param_frame)
        param_row.setContentsMargins(0, 0, 0, 0)
        param_row.setSpacing(8)

        param_title = QLabel("执行参数")
        param_title.setObjectName("fieldLabel")
        param_title.setToolTip("MoveAbsolute 运动参数，仅从手模式生效")
        param_row.addWidget(param_title)

        self.vel_spin = self._make_param_spin(0.15, 0.05, "速度 --vel，默认 0.15")
        self.acc_spin = self._make_param_spin(0.30, 0.10, "加速度 --acc，默认 0.30")
        self.jerk_spin = self._make_param_spin(0.30, 0.10, "加加速度 --jerk，默认 0.30")
        param_row.addWidget(self._labeled_widget("速度", self.vel_spin))
        param_row.addWidget(self._labeled_widget("加速度", self.acc_spin))
        param_row.addWidget(self._labeled_widget("加加速度", self.jerk_spin))
        param_row.addStretch(1)

        param_hint = QLabel("仅从手生效")
        param_hint.setObjectName("hintLabel")
        param_row.addWidget(param_hint)

        card.addWidget(self.param_frame)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["路点名称", "关节角度"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setFixedHeight(34)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        # 空状态 + 表格切换
        self.table_stack = QStackedWidget()
        self.table_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table_stack.addWidget(self._build_empty_state())
        self.table_stack.addWidget(self.table)
        self.table_stack.setCurrentIndex(0)
        card.addWidget(self.table_stack, 1)

        # 底部操作行
        exec_row = QHBoxLayout()
        exec_row.setSpacing(8)
        self.wp_count_label = QLabel("0 个路点")
        self.wp_count_label.setObjectName("countBadge")
        exec_row.addWidget(self.wp_count_label)
        exec_row.addStretch()

        self.exec_btn = QPushButton("▶  执行路点")
        self.exec_btn.setObjectName("execBtn")
        self.exec_btn.setCursor(Qt.PointingHandCursor)
        self.exec_btn.setToolTip("向当前选中的执行目标下发所选路点")
        self.exec_btn.setEnabled(False)
        self.exec_btn.clicked.connect(self._execute_waypoint)
        exec_row.addWidget(self.exec_btn)

        self.stop_btn = QPushButton("🛑  急停")
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setToolTip("立即停止当前运动")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._emergency_stop)
        exec_row.addWidget(self.stop_btn)
        card.addLayout(exec_row)

        return card

    @staticmethod
    def _build_empty_state() -> QWidget:
        """路点列表的空状态占位"""
        empty = QFrame()
        empty.setObjectName("emptyState")

        layout = QVBoxLayout(empty)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)
        layout.addStretch(1)

        icon = QLabel("📄")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 26px; background: transparent;")
        layout.addWidget(icon)

        title = QLabel("尚未加载路点")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("拖入上方区域或点击「选择文件」，随后选择归属目标")
        hint.setObjectName("emptyHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)
        return empty

    # ---------- 日志 ----------
    def _log(self, msg: str):
        self.signal_log.emit(msg)

    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{ts}] {msg}")

    # ---------- 目标选择辅助 ----------
    @staticmethod
    def _repolish(widget: QWidget):
        """让动态属性/伪状态对应的 QSS 立即生效"""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    @staticmethod
    def _target_text(key: Optional[Tuple[str, int]]) -> str:
        if not key:
            return "未选择"
        kind, idx = key
        if kind == "arm":
            return f"从臂 {idx}"
        return "左手" if idx == 0 else "右手"

    def _choose_target(self, global_pos=None) -> Optional[Tuple[str, int]]:
        """弹出目标菜单选择文件归属，取消返回 None"""
        menu = QMenu(self)
        if self.mode == 1:
            options = [(f"{ARM_COLORS[i]['icon']} 从臂 {i + 1}", ("arm", i + 1)) for i in range(4)]
        else:
            options = [("👈 左手", ("hand", 0)), ("👉 右手", ("hand", 1))]
        for label, key in options:
            action = menu.addAction(label)
            action.setData(key)
        pos = global_pos or self.drop_zone.mapToGlobal(self.drop_zone.rect().bottomLeft())
        chosen = menu.exec_(pos)
        return chosen.data() if chosen else None

    def _clear_waypoints(self):
        self.waypoints = []
        self.current_target = None
        self.loaded_filename = ""
        self.loaded_file_path = ""
        self.executed_names.clear()
        self.drop_zone.set_target("未选择")
        self._refresh_waypoint_view()

    def _refresh_waypoint_view(self):
        """刷新表格、拖拽区、计数与已执行状态"""
        self.table.setRowCount(0)
        for name, angles in self.waypoints:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            angle_str = ", ".join(f"{a:.4f}" for a in angles)
            item = QTableWidgetItem(angle_str)
            item.setToolTip(angle_str)
            self.table.setItem(row, 1, item)
            if name in self.executed_names:
                self._style_executed_row(row)

        self.drop_zone.set_target(self._target_text(self.current_target))
        self.drop_zone.set_file(self.loaded_filename, len(self.waypoints))
        self._update_count_label()
        self.table_stack.setCurrentIndex(1 if self.waypoints else 0)
        if self.waypoints:
            self.table.selectRow(0)
        self._update_exec_btn()

    def _update_count_label(self):
        text = f"{len(self.waypoints)} 个路点"
        done = len(self.executed_names)
        if done:
            text += f" · 已执行 {done}"
        self.wp_count_label.setText(text)

    def _style_executed_row(self, row: int):
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                continue
            item.setBackground(QColor("#ECFDF5"))
            item.setForeground(QColor("#047857"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    def _mark_executed(self, wp_name: str):
        """标记已执行路点，用绿色区分"""
        if wp_name in self.executed_names:
            return
        self.executed_names.add(wp_name)
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == wp_name:
                self._style_executed_row(row)
                break
        self._update_count_label()

    # ---------- 模式切换 ----------
    def _style_mode_buttons(self):
        """同步模式按钮的选中态（样式由 #segBtn:checked 决定）"""
        self.mode_btn_master.setChecked(self.mode == 0)
        self.mode_btn_slave.setChecked(self.mode == 1)
        for btn in (self.mode_btn_master, self.mode_btn_slave):
            self._repolish(btn)

    def _set_mode(self, mode: int):
        """切换主手/从手模式"""
        if mode == self.mode:
            self._style_mode_buttons()
            return
        self.mode = mode
        self.model = 7 if self.mode == 1 else 2
        self.mode_btn_master.setChecked(mode == 0)
        self.mode_btn_slave.setChecked(mode == 1)
        self._style_mode_buttons()

        # 主手隐藏摆位卡片与执行参数，从手显示
        if hasattr(self, 'pos_card'):
            self.pos_card.setVisible(mode == 1)
        if hasattr(self, 'param_frame'):
            self.param_frame.setVisible(mode == 1)

        # 单目标：模式切换后原归属失效，清空已加载路点
        target_kind = "arm" if mode == 1 else "hand"
        if self.current_target and self.current_target[0] != target_kind:
            self._clear_waypoints()
            self._log("模式切换，已清空当前路点")

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
            self._apply_pos_state(i, self.connected)
        self._update_exec_btn()

    def _update_exec_btn(self):
        has_data = bool(self.waypoints)
        self.exec_btn.setEnabled(self.connected and has_data)
        self.stop_btn.setEnabled(self.connected)
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
            self._set_connection_state("idle", "未连接")
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
        self.connect_btn.setText("连接中…")
        self._set_connection_state("warn", "连接中…")
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
            self._set_connection_state("ok", "已连接")
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
            self._set_connection_state("err", "TCP 失败")
            self._update_ui_state()
            self._log("TCP连接失败，SSH也不会可用")

    def _set_connection_state(self, state: str, text: str):
        """更新连接状态胶囊：state 取 idle / warn / ok / err"""
        self.status_pill.setProperty("state", state)
        self.status_label.setText(text)
        for widget in (self.status_pill, self.status_dot, self.status_label):
            self._repolish(widget)

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
        self._apply_pos_state(arm_id - 1, enabled=not busy, busy=busy)
        for child in self.pos_btns[arm_id - 1].findChildren(QLabel):
            if child.objectName() == "posText":
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

        self._set_pos_label(arm_id, "执行中…", busy=True)
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
        self._set_pos_label(arm_id, f"从臂 {arm_id}")
        self._log(f"从臂{arm_id} 自动摆位完成")

    # ---------- 路点管理 ----------
    def _on_file_dropped(self, file_path: str):
        """文件拖入后先选择归属，再加载"""
        key = self._choose_target(QCursor.pos())
        if key is None:
            self._refresh_waypoint_view()
            return
        self._load_trajectory_file(file_path, key)

    def _load_trajectory_file(self, file_path: str = "", target_key=None):
        """加载路点文件；未指定文件时弹出选择框，未指定归属时弹出目标菜单"""
        if not file_path:
            start_dir = os.path.dirname(self.loaded_file_path) if self.loaded_file_path else os.path.dirname(
                os.path.abspath(__file__))
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择路点文件", start_dir,
                "路点文件 (*.cvt *.cst *.csv *.txt);;所有文件 (*.*)"
            )
            if not file_path:
                return

        key = target_key or self._choose_target()
        if key is None:
            self._refresh_waypoint_view()
            return

        target_text = self._target_text(key)
        self.drop_zone.set_target(target_text)
        self.drop_zone.set_loading(os.path.basename(file_path))
        self._log(f"加载路点文件（{target_text}）: {file_path}")

        self._load_seq += 1
        seq = self._load_seq

        def task():
            waypoints, error = self._parse_trajectory_file(file_path)
            self.signal_file_loaded.emit((seq, key, file_path, waypoints, error))

        threading.Thread(target=task, daemon=True).start()

    @staticmethod
    def _read_text_auto(file_path: str) -> str:
        """按 BOM/编码探测读取文本，兼容 UTF-8、UTF-16 与 GBK"""
        with open(file_path, "rb") as f:
            raw = f.read()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw.decode("utf-16")
        for enc in ("utf-8-sig", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @classmethod
    def _parse_trajectory_file(cls, file_path: str) -> Tuple[List[Tuple[str, List[float]]], Optional[str]]:
        """解析路点文件（cvt/cst/csv/txt）

        - 分隔符自动识别：制表符 / 逗号 / 分号 / 竖线 / 空格
        - 跳过表头、空行、# 与 // 注释
        - 支持「名称 + 关节角」和「纯数值」两种数据行
        返回 (路点列表, 错误信息)
        """
        try:
            text = cls._read_text_auto(file_path)
        except Exception as e:
            return [], f"读取文件失败: {e}"

        raw_items: List[Tuple[str, List[float]]] = []
        for line in text.splitlines():
            line = line.strip().lstrip("\ufeff")
            if not line or line.startswith(("#", "//")):
                continue
            tokens = [t for t in re.split(r"[\s,;|]+", line) if t]
            if not tokens:
                continue

            try:
                # 纯数值行：无名称列
                angles = [float(t) for t in tokens]
                name = ""
            except ValueError:
                name = tokens[0].rstrip(":")
                try:
                    angles = [float(t) for t in tokens[1:]]
                except ValueError:
                    continue  # 表头 / 说明行
            if angles:
                raw_items.append((name, angles))

        if not raw_items:
            return [], "未解析到任何路点，请确认文件包含「名称（可选）+ 关节角」数据行"

        # 名称为空、重复或为通用标签时，统一命名 P1..PN，保证表格与执行查找唯一
        generic = {"", "name", "actpos", "addlpos", "pos", "joint"}
        labels = [name.lower() for name, _ in raw_items]
        if any(label in generic for label in labels) or len(set(labels)) != len(labels):
            return [(f"P{i}", angles) for i, (_, angles) in enumerate(raw_items, 1)], None
        return raw_items, None

    def _on_file_loaded(self, payload):
        seq, key, file_path, waypoints, error = payload
        if seq != self._load_seq:
            return  # 已有更新的加载请求，忽略旧结果

        target_text = self._target_text(key)
        filename = os.path.basename(file_path)

        if error or not waypoints:
            message = error or "文件中未解析到任何路点"
            self._log(f"警告（{target_text}）: {message}")
            self.drop_zone.set_error("文件解析失败")
            QTimer.singleShot(2200, self._refresh_waypoint_view)
            return

        self.current_target = key
        self.waypoints = waypoints
        self.loaded_filename = filename
        self.loaded_file_path = file_path
        self.executed_names.clear()
        self.drop_zone.set_target(target_text)
        self._refresh_waypoint_view()
        self._log(f"成功为 {target_text} 加载 {len(waypoints)} 个路点: {filename}")

    def _execute_waypoint(self):
        if not self.connected:
            QMessageBox.warning(self, "警告", "请先连接远程服务器")
            return
        if not self.current_target:
            QMessageBox.information(self, "提示", "请先拖入路点文件并选择归属目标")
            return

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在路点列表中选中一个路点")
            return

        wp_name = self.table.item(row, 0).text()
        angles = next((ang for n, ang in self.waypoints if n == wp_name), [])
        if not angles:
            QMessageBox.warning(self, "警告", "未找到该路点的关节角数据")
            return

        # 归属决定执行模式与臂号；执行参数在主线程读取后固定
        kind, idx = self.current_target
        mode = 0 if kind == "hand" else 1
        model = 2 if mode == 0 else 7
        arm_id = idx if kind == "arm" else 1
        hand = idx if kind == "hand" else 0
        vel = self.vel_spin.value()
        acc = self.acc_spin.value()
        jerk = self.jerk_spin.value()

        angle_str = ", ".join([f"{a:.4f}" for a in angles])
        self._mark_executed(wp_name)
        self._log(f"执行路点（{self._target_text(self.current_target)}）: {wp_name} 角度: [{angle_str}]")
        self.exec_btn.setEnabled(False)
        self.exec_btn.setText("执行中...")

        def task():
            if mode == 0:
                cmd = _build_master_exec_cmd(angles, hand)
                self._log(f"执行 ({'左手' if hand==0 else '右手'}): {cmd}")
                resp, err = self.tcp.send_and_recv(cmd, timeout=500.0, expected=model)
                if resp:
                    for line in resp.split("\n"):
                        self._log(f"  <- {line}")
                if err:
                    self._log(f"  -> {err}")
            else:
                cmds = _build_slave_exec_cmds(arm_id, angles, vel, acc, jerk)
                for i, cmd in enumerate(cmds, 1):
                    self._log(f"[{i}/7] 发送: {cmd}")
                    resp, err = self.tcp.send_and_recv(cmd, timeout=500.0, expected=model)
                    if resp:
                        for line in resp.split("\n"):
                            self._log(f"  <- {line}")
                    if err:
                        self._log(f"  -> {err}")

            # 所有返回已收到 → 直接保存关节角数据（同一线程）
            self._do_save_after_exec(wp_name, angles, mode, arm_id, hand)
            self.signal_exec_done.emit()

        threading.Thread(target=task, daemon=True).start()

    # ---------- 路点执行完成回调 ----------
    def _on_exec_done(self):
        self.exec_btn.setText("▶  执行路点")
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

    def _do_save_after_exec(self, wp_name: str, waypoint_angles: List[float],
                            mode: int, arm_id: int, hand: int):
        """执行线程中直接调用：收到所有返回后，等 1s 等待日志刷新，SSH 读取实际角度并保存"""
        if not waypoint_angles:
            return

        actual_angles = None
        source = "waypoint"

        try:
            # 等待 1s 让机器人日志文件更新到最新位置
            threading.Event().wait(1)
            if mode == 1 and self.ssh_slave_connected:
                ssh_angles = self.ssh.read_slave(arm_id)
                if ssh_angles:
                    actual_angles = ssh_angles
                    source = "SSH"

            elif mode == 0 and self.ssh_master_connected:
                arm_name = "Left" if hand == 0 else "Right"
                ssh_angles, view_angle = self.ssh.read_master(arm_name)
                if ssh_angles:
                    actual_angles = ssh_angles
                    source = "SSH"
                    if view_angle is not None:
                        self._save_view_angle_to_file(view_angle)

            if actual_angles is None:
                actual_angles = waypoint_angles

            if mode == 1:
                front_8 = actual_angles[:8]
                back_4 = actual_angles[8:12] if len(actual_angles) >= 12 else []
                psm_file = os.path.join(self.data_dir, f"psm{arm_id}_joint.cst")
                inst_file = os.path.join(self.data_dir, f"inst{arm_id}_joint.cst")
                self._write_joint_file(psm_file, front_8, 8, "actpos")
                if back_4:
                    self._write_joint_file(inst_file, back_4, 4, "actpos")
            elif mode == 0:
                filename = "mtm1_joint.cst" if hand == 0 else "mtm2_joint.cst"
                filepath = os.path.join(self.data_dir, filename)
                self._write_joint_file(filepath, actual_angles, 7, "addlpos")

            self._log(f"路点 [{wp_name}] 数据已保存 [{source}]")
        except Exception as e:
            self._log(f"执行后保存关节角失败: {e}")

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
            for cmd in ["{Stop}", "{Start}", "{Clear}"]:
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
    app.setWindowIcon(QIcon(_resource_path("app_icon.ico")))
    window = AutoKinematicsWindow()
    window.show()
    sys.exit(app.exec_())
