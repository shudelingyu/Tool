#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import datetime
import threading
import tempfile
import traceback
import faulthandler
import paramiko
import json
from collections import deque
# 注意：pandas 需在 PyQt5 之前导入，避免其 C 扩展与 Qt 的加载顺序问题
import pandas as pd
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QLineEdit,
                             QFileDialog, QInputDialog, QMessageBox, QProgressBar, QSpinBox, QSplitter,
                            QAbstractItemView, QGroupBox, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QComboBox, QSizePolicy,
                             QRadioButton, QStackedWidget, QTabWidget, QHeaderView,
                             QShortcut, QMenu, QAction, QToolButton, QTabBar,
                             QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QMimeData, QEvent, QSize, QRectF, QPointF
from PyQt5.QtGui import (QDrag, QFont, QIcon, QPixmap, QPainter, QPen, QColor,
                         QPainterPath, QCursor)
try:
    from PyQt5 import sip
except ImportError:  # 兼容旧版本 PyQt5
    import sip
import pyqtgraph as pg

# 设置 PyQtGraph 全局背景白色、前景黑色
pg.setConfigOptions(background='w', foreground='k')
pg.setConfigOptions(antialias=True)
# 左键拖动=平移，中键拖动=框选放大（RectMode），右键拖动=缩放；右键菜单 Mouse Mode 可切换
pg.setConfigOptions(leftButtonPan=False)

# ==================== 全局设计系统（现代扁平化浅色主题） ====================
# 色彩规范：主色 #2563EB（操作引导）/ 背景 #F1F5F9 / 卡片 #FFFFFF /
# 文字 #1E293B·#475569·#64748B（三级层次）/ 语义色：危险 #DC2626、选中 #DBEAFE
MODERN_QSS = """
/* ---------- 基础容器 ---------- */
QMainWindow, QDialog { background-color: #F1F5F9; }
QMessageBox, QInputDialog { background-color: #FFFFFF; }
/* 不在此处指定 font-size：全局字号由 app.setFont() 统一设置，
   否则会覆盖子控件继承来的字号，导致局部字号调整失效 */
QWidget { color: #1E293B; }

/* ---------- 左侧控制面板：紧凑字号与内边距，避免窄栏内元素拥挤 ----------
   注：Qt 样式表的 font-size 不会自动向下继承，必须逐个控件类型显式指定 */
QWidget#leftPanel QLabel, QWidget#leftPanel QGroupBox,
QWidget#leftPanel QLineEdit, QWidget#leftPanel QSpinBox,
QWidget#leftPanel QComboBox, QWidget#leftPanel QPushButton,
QWidget#leftPanel QCheckBox, QWidget#leftPanel QRadioButton,
QWidget#leftPanel QTreeWidget { font-size: 8pt; }
/* 面板标题保持醒目（需比上面的选择器更具体才能覆盖） */
QWidget#leftPanel QLabel#appTitle { font-size: 15pt; font-weight: bold; color: #1D4ED8; }
QWidget#leftPanel QLineEdit, QWidget#leftPanel QSpinBox, QWidget#leftPanel QComboBox {
    padding: 3px 6px; min-height: 18px;
}

QToolTip {
    background-color: #1E293B; color: #F8FAFC;
    border: 1px solid #334155; border-radius: 4px;
    padding: 5px 8px; font-size: 9pt;
}
QStatusBar { background-color: #FFFFFF; border-top: 1px solid #E2E8F0; color: #64748B; }
QStatusBar::item { border: none; }

/* ---------- 按钮（默认/主操作/危险/图标 四级） ---------- */
QPushButton {
    background-color: #FFFFFF; border: 1px solid #CBD5E1;
    border-radius: 6px; padding: 5px 14px; color: #334155;
}
QPushButton:hover   { background-color: #F8FAFC; border-color: #94A3B8; }
QPushButton:pressed { background-color: #E2E8F0; }
QPushButton:focus   { border-color: #2563EB; }
QPushButton:disabled { color: #94A3B8; background-color: #F8FAFC; border-color: #E2E8F0; }

QPushButton[class="primary"] {
    background-color: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600;
}
QPushButton[class="primary"]:hover   { background-color: #1D4ED8; border-color: #1D4ED8; }
QPushButton[class="primary"]:pressed { background-color: #1E40AF; border-color: #1E40AF; }
QPushButton[class="primary"]:disabled{ background-color: #93C5FD; border-color: #93C5FD; color: #EFF6FF; }

QPushButton[class="danger"] { color: #DC2626; border-color: #FECACA; }
QPushButton[class="danger"]:hover   { background-color: #FEF2F2; border-color: #FCA5A5; }
QPushButton[class="danger"]:pressed { background-color: #FEE2E2; }
QPushButton[class="danger"]:disabled { color: #FCA5A5; border-color: #FEE2E2; }

QPushButton[class="icon"] {
    background-color: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 3px 6px; color: #475569;
}
QPushButton[class="icon"]:hover   { background-color: #E2E8F0; border-color: #CBD5E1; }
QPushButton[class="icon"]:pressed { background-color: #CBD5E1; }
QPushButton[class="icon"]:checked { background-color: #DBEAFE; border-color: #93C5FD; color: #1D4ED8; }
QPushButton[class="icon"]:disabled { color: #CBD5E1; }

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QComboBox {
    background-color: #FFFFFF; border: 1px solid #CBD5E1;
    border-radius: 6px; padding: 4px 8px; min-height: 20px;
    selection-background-color: #2563EB; selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #2563EB; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 6px; padding: 4px; outline: none;
    selection-background-color: #DBEAFE; selection-color: #1D4ED8;
}
QCheckBox, QRadioButton { background-color: transparent; color: #334155; spacing: 6px; }

/* ---------- 分组卡片 ---------- */
QGroupBox {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 8px; margin-top: 11px; padding: 6px;
    font-weight: 600; color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 10px; padding: 0 4px; color: #475569;
}

/* ---------- 进度条 ---------- */
QProgressBar {
    background-color: #E2E8F0; border: none; border-radius: 6px;
    text-align: center; color: #1E293B; font-size: 8pt;
}
QProgressBar::chunk { background-color: #2563EB; border-radius: 6px; }

/* ---------- 标签页（胶囊式） ---------- */
QTabWidget::pane { border: 1px solid #E2E8F0; border-radius: 8px; background-color: #FFFFFF; }
QTabBar { background-color: transparent; }
QTabBar::tab {
    background-color: #E2E8F0; color: #475569;
    padding: 5px 5px; margin: 6px 4px 2px 0;
    border-radius: 6px; border: 1px solid transparent;
}
QTabBar::tab:hover { background-color: #CBD5E1; color: #1E293B; }
QTabBar::tab:selected { background-color: #2563EB; color: #FFFFFF; font-weight: 600; }

/* ---------- 数据列树 ---------- */
QTreeWidget {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 8px; padding: 2px;
    alternate-background-color: #F8FAFC; outline: none;
}
QTreeWidget::item { height: 24px; border-radius: 4px; }
QTreeWidget::item:hover { background-color: #F1F5F9; }
QTreeWidget::item:selected { background-color: #DBEAFE; color: #1D4ED8; }
QHeaderView::section {
    background-color: #F8FAFC; border: none;
    border-bottom: 1px solid #E2E8F0; padding: 5px 6px;
    color: #64748B; font-weight: 600;
}

/* ---------- 滚动条 / 分栏手柄 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #CBD5E1; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #94A3B8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background-color: #E2E8F0; }
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
QSplitter::handle:hover { background-color: #93C5FD; }

/* ---------- 右键菜单 ---------- */
QMenu {
    background-color: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 8px; padding: 6px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; color: #334155; }
QMenu::item:selected { background-color: #DBEAFE; color: #1D4ED8; }
QMenu::separator { height: 1px; background-color: #E2E8F0; margin: 4px 8px; }

/* ---------- 语义标签 ---------- */
/* 标题样式定义在左侧面板规则处（QWidget#leftPanel QLabel#appTitle），
   以保证不被面板的紧凑字号规则覆盖 */
QLabel#sectionLabel { color: #64748B; font-weight: 600; }
QLabel#logoLabel { color: #94A3B8; font-size: 8pt; padding: 4px 0; }
QLabel[class="card"] {
    background-color: #F8FAFC; border: 1px solid #E2E8F0;
    border-radius: 6px; padding: 8px; color: #475569;
}
"""


def close_x_icon(size=11, color="#475569", hover="#DC2626", weight=1.5):
    """矢量 ✕ 关闭图标：4 倍超采样后交给 Qt 缩放，100%~400% 缩放下都锐利。

    不用 "✖"/"✕" 字符——字体回退后会变成又粗又黑的大叉，和扁平风格打架。
    悬停时 Qt 自动切到 Active 那张（变红），无需额外事件处理。
    """
    ss = 4.0                       # 超采样倍数
    icon = QIcon()
    for state, col in ((QIcon.Normal, color), (QIcon.Active, hover), (QIcon.Selected, hover)):
        edge = int(size * ss)
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(col), weight * ss)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = int(edge * 0.15)        # 端点内缩，否则圆头会被裁掉
        p.drawLine(m, m, edge - m, edge - m)
        p.drawLine(edge - m, m, m, edge - m)
        p.end()
        # 必须画完再设：DPR 会让 QPainter 的坐标一起放大，先设的话第二笔会画出画布
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


def split_icon(divider="vertical", size=16, color="#475569", weight=1.25, fill_alpha=42):
    """矢量分栏图标：圆角外框 + 中间分隔线，新分栏一侧淡填充以表明方向。

    divider="vertical"   竖线分隔 → 左右两栏（对应"水平分栏"）
    divider="horizontal" 横线分隔 → 上下两栏（对应"垂直分栏"）
    与 close_x_icon 一样用 4 倍超采样，保证高 DPI 下锐利。
    """
    ss = 4.0
    icon = QIcon()
    for state, col in ((QIcon.Normal, color), (QIcon.Active, color), (QIcon.Selected, color)):
        edge = int(size * ss)
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)

        m = edge * 0.13                 # 外边距
        w = edge - 2 * m
        r = w * 0.22                    # 圆角半径
        rect = QRectF(m, m, w, w)
        c = QColor(col)

        # 用裁剪路径填充"新分栏"一侧，保证圆角与外框吻合
        clip = QPainterPath()
        clip.addRoundedRect(rect, r, r)
        p.setClipPath(clip)
        tint = QColor(c.red(), c.green(), c.blue(), fill_alpha)
        if divider == "vertical":
            p.fillRect(QRectF(rect.center().x(), rect.top(), rect.width() / 2, rect.height()), tint)
        else:
            p.fillRect(QRectF(rect.left(), rect.center().y(), rect.width(), rect.height() / 2), tint)

        # 外框 + 分隔线
        pen = QPen(c, weight * ss)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, r, r)
        if divider == "vertical":
            x = rect.center().x()
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        else:
            y = rect.center().y()
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        p.end()
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


def _stroke_pen(color, width):
    """统一的圆头圆角笔画，保证整套图标视觉一致。"""
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def plus_icon(size=16, color="#475569", weight=1.5):
    """矢量“新建”图标：圆角加号，与分栏图标同一套笔画风格。"""
    ss = 4.0
    icon = QIcon()
    edge = int(size * ss)
    for state in (QIcon.Normal, QIcon.Active, QIcon.Selected):
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = edge * 0.20
        c = edge / 2.0
        p.setPen(_stroke_pen(color, weight * ss))
        p.drawLine(QPointF(c, m), QPointF(c, edge - m))
        p.drawLine(QPointF(m, c), QPointF(edge - m, c))
        p.end()
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


def cursor_icon(index=0, size=16, color=None, weight=1.4):
    """矢量游标图标：顶端向下三角（播放头/游标）+ 竖线。

    index=0 → 游标A（红），index=1 → 游标B（蓝），与绘图区游标颜色一致，
    便于在工具栏上快速区分两个游标。
    """
    color = color or ("#DC2626" if index == 0 else "#2563EB")
    ss = 4.0
    icon = QIcon()
    edge = int(size * ss)
    for state in (QIcon.Normal, QIcon.Active, QIcon.Selected):
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = edge / 2.0
        top = edge * 0.16
        bot = edge * 0.88
        hw = edge * 0.16      # 三角半宽
        th = edge * 0.24      # 三角高
        # 竖线（从三角内部起，避免圆头端点外露）
        p.setPen(_stroke_pen(color, weight * ss))
        p.drawLine(QPointF(c, top + th * 0.6), QPointF(c, bot))
        # 顶端向下三角
        tri = QPainterPath()
        tri.moveTo(c, top + th)
        tri.lineTo(c - hw, top)
        tri.lineTo(c + hw, top)
        tri.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(tri)
        p.end()
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


def clock_icon(size=16, color="#475569", weight=1.5):
    """矢量时间跳转图标：圆环 + 时针分针。"""
    ss = 4.0
    icon = QIcon()
    edge = int(size * ss)
    for state in (QIcon.Normal, QIcon.Active, QIcon.Selected):
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = edge * 0.16
        rect = QRectF(m, m, edge - 2 * m, edge - 2 * m)
        p.setPen(_stroke_pen(color, weight * ss))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)
        cc = rect.center()
        p.drawLine(QPointF(cc.x(), cc.y()), QPointF(cc.x(), cc.y() - rect.height() * 0.30))
        p.drawLine(QPointF(cc.x(), cc.y()), QPointF(cc.x() + rect.width() * 0.22, cc.y()))
        p.end()
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


def follow_icon(size=16, color="#475569", weight=1.5):
    """矢量“跟随最新数据”图标：双右箭头（»），表示视图持续推进到最新数据"""
    ss = 4.0
    icon = QIcon()
    edge = int(size * ss)
    for state in (QIcon.Normal, QIcon.Active, QIcon.Selected):
        pm = QPixmap(edge, edge)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        p.setPen(_stroke_pen(color, weight * ss))
        for dx in (0.0, 0.30):
            x0 = edge * (0.22 + dx)
            x1 = edge * (0.46 + dx)
            chevron = QPainterPath()
            chevron.moveTo(x0, edge * 0.26)
            chevron.lineTo(x1, edge * 0.50)
            chevron.lineTo(x0, edge * 0.74)
            p.drawPath(chevron)
        p.end()
        pm.setDevicePixelRatio(ss)
        icon.addPixmap(pm, state)
    return icon


# ==================== 崩溃诊断与日志 ====================
# 打包为窗口程序（console=False）后 stdout/stderr 不可见，静默崩溃时没有任何线索。
# 这里把日志写到 exe 同级的 logs 目录（不可写时回退系统临时目录），
# 并用 faulthandler 捕获原生崩溃（访问违例/非法指令）的 C 级堆栈。
_LOG_HANDLE = None
_LOG_PATH = None
_LOG_FD = None
# 异常去重与弹窗限流：定时器/绘图回调里反复抛错时，
# 若无限制地弹模态框会把程序卡死（"弹窗风暴"）
_EXC_SEEN = {}
_EXC_MAX_LOGS = 3     # 同一异常最多记录的堆栈次数
_STACK_LOG_COUNT = 0
_STACK_LOG_MAX = 20   # 单次运行最多记录的堆栈总数，防止日志被刷爆
_DIALOG_COUNT = 0
_DIALOG_MAX = 3       # 单次运行最多弹出的错误框数量


def _show_error_dialog_later():
    """在事件循环空闲时弹出错误提示（避免在异常抛出点嵌套事件循环）"""
    try:
        QMessageBox.critical(None, "程序错误",
                             f"发生未处理的错误，详情请查看日志：\n{_LOG_PATH}")
    except Exception:
        pass


def qt_alive(obj):
    """判断 PyQt 包装对象底层 C++ 对象是否仍然有效。

    PyQt 中 Python 包装对象可能比底层 C++ 对象存活更久（如控件被 deleteLater
    销毁后），此时访问该对象会触发 access violation 导致进程崩溃。
    """
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except Exception:
        return True  # 无法判断时按有效处理（非 PyQt 对象）


def get_app_base_dir():
    """返回程序基准目录：打包后为 exe 所在目录，开发环境为脚本所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _open_log_file():
    """打开日志文件（进程内仅打开一次），返回文件句柄或 None

    使用追加 + 每次写入单次系统调用的方式，避免与 faulthandler 的输出交错，
    导致日志内容被写乱、掩盖崩溃线索。
    """
    global _LOG_HANDLE, _LOG_PATH, _LOG_FD
    if _LOG_HANDLE is not None:
        return _LOG_HANDLE
    for d in (os.path.join(get_app_base_dir(), 'logs'),
              os.path.join(tempfile.gettempdir(), 'logAnalysis_logs')):
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, 'logAnalysis.log')
            _LOG_FD = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            # faulthandler 需要一个文件对象，使用同一描述符的副本，语义一致
            _LOG_HANDLE = os.fdopen(os.dup(_LOG_FD), 'a', encoding='utf-8', errors='replace')
            _LOG_PATH = path
            return _LOG_HANDLE
        except Exception:
            continue
    return None


def log(msg):
    """写入带时间戳的运行日志（原子写入，避免与原生崩溃堆栈交错）"""
    global _LOG_FD
    if _LOG_FD is None:
        _open_log_file()
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}\n"
    if _LOG_FD is not None:
        try:
            os.write(_LOG_FD, line.encode('utf-8', 'replace'))
        except Exception:
            pass
    try:
        print(line, end='')
    except Exception:
        pass


def setup_crash_logging():
    """安装崩溃捕获：Python 异常 + 子线程异常 + 原生崩溃（faulthandler）"""
    fh = _open_log_file()
    if fh is not None:
        try:
            faulthandler.enable(fh)  # 原生崩溃也会写入 C 级堆栈
        except Exception:
            pass

    log('=' * 70)
    log(f"程序启动 | frozen={getattr(sys, 'frozen', False)} | Python={sys.version.split()[0]}")
    log(f"可执行文件: {sys.executable}")
    log(f"日志文件: {_LOG_PATH}")

    def _excepthook(exc_type, exc_value, exc_tb):
        global _DIALOG_COUNT, _STACK_LOG_COUNT
        text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        # 去重计数：避免反复抛错时日志刷屏
        key = (getattr(exc_type, '__name__', '?'), str(exc_value)[:200])
        n = _EXC_SEEN.get(key, 0) + 1
        _EXC_SEEN[key] = n
        if n == 1 and _STACK_LOG_COUNT >= _STACK_LOG_MAX:
            log(f'已记录 {_STACK_LOG_MAX} 条异常堆栈，后续异常仅计数、不再输出')
        if n <= _EXC_MAX_LOGS and _STACK_LOG_COUNT < _STACK_LOG_MAX:
            _STACK_LOG_COUNT += 1
            log(f'未捕获的 Python 异常（第 {n} 次）:\n{text}')
        if n > _EXC_MAX_LOGS:
            return
        # 弹窗限流：反复抛错（如定时器回调中）时，大量模态框会启动嵌套事件循环
        # 把程序卡死，因此总量封顶，且不在 Qt 绘制上下文中弹窗
        if _DIALOG_COUNT >= _DIALOG_MAX:
            return
        if 'pyqtgraph' in text or 'prepareForPaint' in text or 'paintEvent' in text:
            log('（异常源自绘图控件内部，仅记录日志，不弹窗以避免二次崩溃）')
            return
        _DIALOG_COUNT += 1
        QTimer.singleShot(0, _show_error_dialog_later)

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        text = ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log(f"子线程 [{getattr(args.thread, 'name', '?')}] 未捕获异常:\n" + text)

    try:
        threading.excepthook = _thread_excepthook
    except Exception:
        pass

    _install_unhandled_filter()


# 保持滤波函数引用，避免被垃圾回收后回调失效
_UNHANDLED_HANDLER = None


def module_of_address(addr):
    """查询代码地址所属模块（DLL/exe）文件名。

    崩溃地址落在哪个模块，能直接判断是 Qt、GPU 驱动、pandas/numpy 还是解释器本身。
    """
    if sys.platform != 'win32' or not addr:
        return ''
    try:
        import ctypes

        class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p),
                        ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", ctypes.c_ulong),
                        ("RegionSize", ctypes.c_size_t),
                        ("State", ctypes.c_ulong),
                        ("Protect", ctypes.c_ulong),
                        ("Type", ctypes.c_ulong)]

        mbi = _MEMORY_BASIC_INFORMATION()
        k32 = ctypes.windll.kernel32
        k32.VirtualQuery.argtypes = [ctypes.c_void_p,
                                     ctypes.POINTER(_MEMORY_BASIC_INFORMATION),
                                     ctypes.c_size_t]
        k32.VirtualQuery.restype = ctypes.c_size_t
        if not k32.VirtualQuery(ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            return ''
        buf = ctypes.create_unicode_buffer(512)
        if k32.GetModuleFileNameW(ctypes.c_void_p(mbi.AllocationBase), buf, 512):
            return os.path.basename(buf.value)
    except Exception:
        pass
    return ''


def _install_unhandled_filter():
    """安装 Windows 未处理异常过滤器。

    faulthandler 报告的是 first-chance 异常（可能被上层 SEH 处理掉、属良性），
    这里捕获的是最终无人处理的致命异常，可记录异常代码与地址，
    用于区分"良性 AV"和"真正的致命崩溃"。
    """
    if sys.platform != 'win32':
        return
    global _UNHANDLED_HANDLER
    try:
        import ctypes
        from ctypes import wintypes  # noqa: F401

        class _EXCEPTION_RECORD(ctypes.Structure):
            _fields_ = [("ExceptionCode", ctypes.c_ulong),
                        ("ExceptionFlags", ctypes.c_ulong),
                        ("ExceptionRecord", ctypes.c_void_p),
                        ("ExceptionAddress", ctypes.c_void_p),
                        ("NumberParameters", ctypes.c_ulong),
                        ("ExceptionInformation", ctypes.c_void_p * 15)]

        class _EXCEPTION_POINTERS(ctypes.Structure):
            _fields_ = [("ExceptionRecord", ctypes.POINTER(_EXCEPTION_RECORD)),
                        ("ContextRecord", ctypes.c_void_p)]

        EXCEPTION_CONTINUE_SEARCH = 0

        def _filter(ptr):
            try:
                rec = ptr.contents.ExceptionRecord.contents
                code = rec.ExceptionCode & 0xFFFFFFFF
                addr = rec.ExceptionAddress or 0
                names = {0xC0000005: 'access violation',
                         0xC00000FD: 'stack overflow',
                         0xC0000374: 'heap corruption',
                         0xC0000409: 'stack buffer overrun / fail-fast'}
                # 访问违例时，ExceptionInformation[1] 才是实际出错的内存地址
                fault = 0
                if code == 0xC0000005:
                    try:
                        fault = rec.ExceptionInformation[1] or 0
                    except Exception:
                        fault = 0
                detail = (f"!! 致命原生异常: 代码=0x{code:08X} "
                          f"({names.get(code, 'unknown')}) "
                          f"指令地址=0x{addr:X} [{module_of_address(addr) or '未知模块'}]")
                if fault:
                    detail += f" 访问地址=0x{fault:X}"
                log(detail)
                try:
                    faulthandler.dump_traceback(file=_open_log_file(), all_threads=True)
                except Exception:
                    pass
            except Exception:
                pass
            return EXCEPTION_CONTINUE_SEARCH

        _UNHANDLED_HANDLER = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.POINTER(_EXCEPTION_POINTERS))(_filter)
        ctypes.windll.kernel32.SetUnhandledExceptionFilter(_UNHANDLED_HANDLER)
    except Exception as e:
        log(f"安装未处理异常过滤器失败: {e}")


# ==================== 日志解析模块（配置文件驱动） ====================
TIMESTAMP_PAT = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*')
MASTER_NUM_PAT = re.compile(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?')

# ========== 配置文件驱动 ==========
class FormatConfig:
    """从 JSON 配置加载数据格式定义，动态生成列名和解析规则。"""

    def __init__(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self._raw = json.load(f)
        self._cols_cache = {}
        self._simple_to_full = None
        
    def get_online_device_types(self):
        """返回在线模式支持的设备类型列表（按配置顺序）"""
        return list(self._raw.get('online_paths', {}).keys())

    def get_online_paths(self, device_type):
        """根据设备类型返回 [(prefix, remote_path), ...]"""
        paths_cfg = self._raw.get('online_paths', {}).get(device_type, [])
        return [(item['prefix'], item['path']) for item in paths_cfg]

    # ---- 列名生成 ----

    def get_columns(self, fmt_name, variant=None):
        """获取指定格式的列名列表。variant='simple' 仅对 slave 有效。"""
        cache_key = (fmt_name, variant)
        if cache_key in self._cols_cache:
            return self._cols_cache[cache_key]

        fmt = self._raw.get(fmt_name)
        if fmt is None:
            return []

        cols = []
        if fmt_name == 'master':
            for field in fmt['fields']:
                name, cnt = field['name'], field['count']
                if cnt == 1:
                    cols.append(name)
                else:
                    cols.extend([f'{name}_{i}' for i in range(cnt)])
        else:
            # slave / boom: array_vars + flat_vars
            for var in fmt.get('array_vars', []):
                name, cnt = var['name'], var['count']
                if variant == 'simple':
                    s = fmt['simple']['array_start']
                    e = fmt['simple']['array_end']
                    cols.extend([f'{name}[{i}]' for i in range(s, e)])
                else:
                    cols.extend([f'{name}[{i}]' for i in range(cnt)])
            for var in fmt.get('flat_vars', []):
                name, cnt = var['name'], var['count']
                if cnt == 1:
                    cols.append(name)
                else:
                    cols.extend([f'{name}[{i}]' for i in range(cnt)])

        self._cols_cache[cache_key] = cols
        return cols

    def get_simple_to_full_indices(self):
        """92 列简单格式 → 142 列全格式的索引映射。"""
        if self._simple_to_full is None:
            full = self.get_columns('slave')
            simple = self.get_columns('slave', 'simple')
            self._simple_to_full = [full.index(c) for c in simple]
        return self._simple_to_full

    def get_field_defs(self, fmt_name):
        """获取 master 的字段定义列表 [(name, count, has_label), ...]"""
        fmt = self._raw.get(fmt_name)
        if fmt is None or 'fields' not in fmt:
            return []
        return [(f['name'], f['count'], f.get('has_label', True)) for f in fmt['fields']]

    def get_total_count(self, fmt_name, variant=None):
        """获取某格式的总列数。"""
        cols = self.get_columns(fmt_name, variant)
        return len(cols)

    # ---- 格式检测 ----

    def detect_format(self, data_part):
        """根据 data_part 判断日志格式，返回 (fmt_name, variant) 或 (None, None)。"""
        for fmt_name, fmt in self._raw.items():
            # 跳过 lout（ADS 单独处理）
            if 'detect_regex' in fmt:
                continue
            detect = fmt.get('detect', {})
            prefix = detect.get('prefix')  # None=master, ","=slave/boom
            counts = detect.get('counts', [])
            if prefix is None:
                # master: 不以逗号开头
                if not data_part.startswith(','):
                    return fmt_name, None
            else:
                # slave/boom: 以逗号开头，且列数匹配
                if data_part.startswith(prefix):
                    # 用 count(',') 代替 split 计数，避免创建临时列表
                    n = data_part.count(',')
                    if n in counts:
                        variant = 'simple' if fmt_name == 'slave' and n == 92 else None
                        return fmt_name, variant
        return None, None

    # ---- 值解析 ----

    def parse_values(self, fmt_name, data_part, variant=None):
        """按配置解析一行数据，返回 (cols, values) 或 (None, None)。"""
        fmt = self._raw.get(fmt_name)
        if fmt is None:
            return None, None

        if fmt_name == 'master':
            return self._parse_master(data_part, fmt)
        elif fmt_name == 'slave':
            return self._parse_slave(data_part, variant)
        elif fmt_name == 'boom':
            return self._parse_boom(data_part, fmt)
        return None, None

    def _parse_number(self, tok):
        tok = tok.strip().rstrip(',')
        if not tok:
            return np.nan
        try:
            if '.' in tok or 'e' in tok.lower():
                return float(tok)
            return int(tok)
        except Exception:
            try:
                return float(tok)
            except Exception:
                return np.nan

    def _parse_slave(self, data_part, variant=None):
        if not data_part.startswith(','):
            return None, None
        parts = data_part[1:].split(',')
        n = len(parts)
        cols = self.get_columns('slave', variant)
        expected = len(cols)
        if n != expected:
            return None, None

        values = [self._parse_number(p) for p in parts]

        if variant == 'simple':
            # 92→142 列扩展：把简单格式值填入全格式对应位置
            indices = self.get_simple_to_full_indices()
            full_values = [0.0] * len(self.get_columns('slave'))
            for idx_simple, val in enumerate(values):
                full_values[indices[idx_simple]] = val
            return self.get_columns('slave'), full_values

        return cols, values

    def _parse_boom(self, data_part, fmt):
        if not data_part.startswith(','):
            return None, None
        parts = data_part[1:].split(',')
        cols = self.get_columns('boom')
        if len(parts) != len(cols):
            return None, None
        values = [self._parse_number(p) for p in parts]
        return cols, values

    def _parse_master(self, data_part, fmt):
        parts = data_part.strip().split()
        if not parts:
            return None, None

        fields = self.get_field_defs('master')
        values = []
        i = 0
        for name, cnt, has_label in fields:
            if has_label and i < len(parts) and parts[i] == name:
                i += 1
            for _ in range(cnt):
                if i >= len(parts):
                    return None, None
                values.append(self._parse_number(parts[i]))
                i += 1
        return self.get_columns('master'), values


def parse_timestamp(line: str):
    m = TIMESTAMP_PAT.match(line)
    if m:
        return m.group(1), line[m.end():]
    return None, line

def get_config_path():
    """定位数据格式配置文件，按优先级返回第一个存在的路径：
    1) exe/脚本同级 configs  —— 便于用户现场覆盖配置
    2) 打包内置资源(_MEIPASS)/configs —— 保证 exe 单独拷贝到其他电脑也能用
    """
    if getattr(sys, 'frozen', False):
        candidates = [os.path.join(os.path.dirname(sys.executable), 'configs', 'data_formats.json')]
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, 'configs', 'data_formats.json'))
    else:
        candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'configs', 'data_formats.json')]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]  # 均不存在时返回首选路径，便于日志提示


# 加载配置文件（可能位于 exe 同级目录，或打包内置的 configs 资源中）
_CONFIG_PATH = get_config_path()
config = None
try:
    if os.path.exists(_CONFIG_PATH):
        config = FormatConfig(_CONFIG_PATH)
        log(f"配置文件加载成功: {_CONFIG_PATH}")
    else:
        log(f"警告：配置文件未找到，路径 {_CONFIG_PATH}（将无法解析日志格式）")
except Exception as _cfg_err:
    # 配置损坏不应导致程序无法启动
    log(f"警告：配置文件解析失败（{_CONFIG_PATH}）：{_cfg_err}")

def parse_slave_line_fast(data_part: str):
    return config.parse_values('slave', data_part) if config else (None, None)

def parse_master_line_fast(data_part: str):
    return config.parse_values('master', data_part) if config else (None, None)

def parse_boom_line_fast(data_part: str):
    return config.parse_values('boom', data_part) if config else (None, None)

# ...existing code...
def parse_lout_line_fast(line: str):
    """
    解析类似：
      [ADS]:0,cmdTorque: -0.00292011 0.0805256
      [ADS]:1,cmdTorque: -0.000663661 0.082467
    或者键值用逗号分隔的形式 key:val1,val2
    返回 (cols, vals) 或 (None, None)。
    列名格式：<model>_<key>（单值）或 <model>_<key>_<idx>（多值，从1开始）
    """
    # 先捕获 model 和余下字符串
    m = re.search(r'\[ADS\]\s*:\s*([A-Za-z0-9_]+)\s*,\s*(.*)', line)
    if not m:
        m = re.search(r'ADS\s*:\s*([A-Za-z0-9_]+)\s*,\s*(.*)', line)
        if not m:
            return None, None
    model = m.group(1)
    rest = m.group(2)

    # 匹配 key: 后面跟一串数值（数值间可用空格或逗号分隔）
    # 捕获 value 群组（可能包含多个数，通过空格或逗号分隔）
    pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?(?:[ \t,]+[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)*)')
    pairs = pattern.findall(rest)
    if not pairs:
        return None, None

    cols = []
    vals = []
    for key, vals_str in pairs:
        # 拆分多个数值，支持逗号或任意空白分隔
        parts = [p for p in re.split(r'[,\s]+', vals_str.strip()) if p != '']
        if not parts:
            # 没有数值则跳过
            continue
        if len(parts) == 1:
            colname = f"{model}_{key}"
            cols.append(colname)
            try:
                vals.append(float(parts[0]))
            except Exception:
                vals.append(np.nan)
        else:
            for i, p in enumerate(parts):
                colname = f"{model}_{key}_{i+1}"
                cols.append(colname)
                try:
                    vals.append(float(p))
                except Exception:
                    vals.append(np.nan)
    if not cols:
        return None, None
    return cols, vals

# ---- DISPLAY 格式解析 ----

def parse_display_line(rest):
    """
    解析 [DISPLAY] 行，格式：
      [DISPLAY]count: <time_val>, name1:[v1, v2, ...], name2:[v1, v2, ...]
    变量名和数组长度均为动态。
    返回 (count_val, cols, vals) 或 (None, None, None)。
    """
    m = re.search(r'\[DISPLAY\]\s*(.*)', rest)
    if not m:
        return None, None, None
    content = m.group(1).strip()
    # 提取 count 值（时间轴）
    count_m = re.match(
        r'count\s*:\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*,\s*(.*)', content
    )
    if not count_m:
        return None, None, None
    count_val = float(count_m.group(1))
    remaining = count_m.group(2)
    # 提取变量数组：name:[v1, v2, ...]
    pattern = re.compile(r'(\w+)\s*:\s*\[([^\]]*)\]\s*,?\s*')
    cols = []
    vals = []
    for name, arr_str in pattern.findall(remaining):
        parts = [p.strip() for p in arr_str.split(',') if p.strip()]
        for i, p in enumerate(parts):
            cols.append(f"{name}[{i}]")
            try:
                vals.append(float(p))
            except Exception:
                vals.append(np.nan)
    return count_val, cols, vals


def parse_log_line(line: str):
    """
    通用解析：先提取行首时间戳（如果有），然后寻找行内所有 [ADS] 片段并分别解析。
    返回列表 [(ts_str, cols, vals), ...]
    """
    ts_str, rest = parse_timestamp(line)
    if not rest:
        return [(ts_str, None, None)]

    results = []

    # 查找行内所有以 [ADS]: 开头的片段（匹配直到下一个 '[' 或行尾）
    ads_iter = re.finditer(r'(\[ADS\]\s*:\s*\d+\s*,[^[]*)', rest)
    ads_found = False
    for m in ads_iter:
        ads_found = True
        seg = m.group(1)
        cols, vals = parse_lout_line_fast(seg)
        if cols is not None and vals is not None:
            results.append((ts_str, cols, vals))

    if ads_found:
        return results

    # 使用配置文件驱动格式检测
    data_part = rest
    if config:
        fmt_name, variant = config.detect_format(data_part)
        if fmt_name:
            cols, vals = config.parse_values(fmt_name, data_part, variant)
            return [(ts_str, cols, vals)]
    return [(ts_str, None, None)]

# ==================== 实时监控线程 ====================
# 无数据超时（秒）：激活记录后超过该时长未读到任何数据，自动停止该臂的读取与记录
NO_DATA_TIMEOUT = 10.0

class LiveThread(QThread):
    new_batch = pyqtSignal(list)     # 批量数据 [(epoch, {col: val}), ...]（已按需过滤列）
    error = pyqtSignal(str, str)     # (臂前缀, 错误信息)
    status = pyqtSignal(str)

    def __init__(self, host, port, username, password, remote_path, arm_prefix=''):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_path = remote_path
        self.arm_prefix = arm_prefix
        self._running = False
        self.ssh = None
        self.sftp = None
        self.file = None
        self.paused = False
        # ---- 按需记录控制 ----
        self.recording_enabled = False  # False=空闲：不读取数据行，仅监控文件状态
        self.active_cols_bare = None    # None=记录全部列（动态格式）；set=仅记录这些裸列名
        self._need_seek_end = False     # 激活记录时先跳到文件末尾，只记录最新数据
        self._last_data_time = None     # 最近一次读到数据的时间（monotonic）

    def set_paused(self, paused):
        self.paused = paused

    def run(self):
        batch = []
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.host, port=self.port, username=self.username,
                             password=self.password, timeout=5)
            self.sftp = self.ssh.open_sftp()
            self.file = self.sftp.open(self.remote_path, 'r')
            self.file.seek(0, 2)
            self._running = True
            self._last_data_time = time.monotonic()
            if self.recording_enabled:
                self.status.emit(f"[{self.arm_prefix}] 已连接，开始实时监控...")
            else:
                self.status.emit(f"[{self.arm_prefix}] 已连接（空闲，拖入曲线后开始记录）")

            last_size = self.sftp.stat(self.remote_path).st_size
            check_counter = 0
            last_ts_str = None  # 保存最近一个有时间戳的字符串
            last_flush = time.monotonic()

            while self._running:
                # 激活记录时跳到文件末尾：只记录拖入曲线之后的最新数据
                if self._need_seek_end:
                    try:
                        self.file.seek(0, 2)
                    except Exception:
                        pass
                    self._need_seek_end = False
                    self._last_data_time = time.monotonic()
                    if batch:
                        self.new_batch.emit(batch)
                        batch = []
                        last_flush = time.monotonic()

                # 空闲模式：该臂当前无活动曲线，不读取数据行（节省 CPU/带宽）
                if not self.recording_enabled:
                    check_counter += 1
                    if check_counter >= 20:  # ~2s 检查一次文件轮转
                        check_counter = 0
                        last_size = self._check_rotation(last_size)
                    self.msleep(100)
                    continue

                line = self.file.readline()
                if line:
                    line = line.strip()
                    if line:
                        self._last_data_time = time.monotonic()
                        check_counter = 0
                        if not self.paused:
                            # 不做抽稀：只解析被拖动绘制的列，数据量已足够小
                            results = parse_log_line(line)
                            for ts_str, cols, vals in results:
                                if cols is None or vals is None:
                                    continue
                                # 优先使用本片段的时间戳；否则沿用上一次的
                                ts_use = ts_str if ts_str else last_ts_str
                                if ts_str:
                                    last_ts_str = ts_str
                                if not ts_use:
                                    epoch = datetime.datetime.now().timestamp()
                                else:
                                    try:
                                        dt = datetime.datetime.strptime(ts_use, '%Y-%m-%d %H:%M:%S.%f')
                                        epoch = dt.timestamp()
                                    except Exception:
                                        try:
                                            dt = datetime.datetime.strptime(ts_use, '%Y-%m-%d %H:%M:%S')
                                            epoch = dt.timestamp()
                                        except Exception:
                                            epoch = datetime.datetime.now().timestamp()
                                data_dict = dict(zip(cols, vals))
                                # 针对性记录：仅记录当前操作的臂上已绘制的列
                                if self.active_cols_bare is not None:
                                    data_dict = {c: v for c, v in data_dict.items()
                                                 if c in self.active_cols_bare}
                                if data_dict:
                                    batch.append((epoch, data_dict))
                else:
                    if batch:
                        self.new_batch.emit(batch)
                        batch = []
                        last_flush = time.monotonic()
                    check_counter += 1
                    if check_counter >= 5:
                        check_counter = 0
                        last_size = self._check_rotation(last_size)
                    # 无数据超时：该臂没有数据时自动停止其读取与记录
                    if self._last_data_time is not None and (
                            time.monotonic() - self._last_data_time > NO_DATA_TIMEOUT):
                        self.status.emit(f"[{self.arm_prefix}] 无数据（超过 {NO_DATA_TIMEOUT:.0f}s），自动停止该臂读取")
                        break
                    self.msleep(10)

                # 批量上报：攒批大幅降低跨线程信号开销（相比逐行发送）
                if batch and (len(batch) >= 200 or time.monotonic() - last_flush >= 0.1):
                    self.new_batch.emit(batch)
                    batch = []
                    last_flush = time.monotonic()
        except Exception as e:
            self.error.emit(self.arm_prefix, str(e))
        finally:
            if batch:
                try:
                    self.new_batch.emit(batch)
                except Exception:
                    pass
            if self.file:
                self.file.close()
            if self.sftp:
                self.sftp.close()
            if self.ssh:
                self.ssh.close()
            self._running = False

    def _check_rotation(self, last_size):
        """检查远程文件是否被截断/轮转，返回新的 last_size。
        仅以"文件变小"判定轮转；mtime 变化属于正常追加，不重开文件
        （旧逻辑按 mtime 重开会 seek 到末尾，丢失刚写入的数据）。"""
        try:
            new_stat = self.sftp.stat(self.remote_path)
            if new_stat.st_size < last_size:
                # 文件被截断或轮转：重新打开并从新文件末尾继续跟踪
                try:
                    self.file.close()
                except Exception:
                    pass
                self.file = self.sftp.open(self.remote_path, 'r')
                self.file.seek(0, 2)
                self.status.emit(f"[{self.arm_prefix}] 检测到日志轮转，已重新连接")
            return new_stat.st_size
        except FileNotFoundError:
            return last_size  # 文件暂时不存在（可能正在轮转），等待重建
        except Exception as e:
            self.error.emit(self.arm_prefix, f"检查文件状态出错: {e}")
            return last_size

    def stop(self):
        self._running = False
        self.quit()
        self.wait()

# ==================== 后台加载线程（离线模式） ====================
# 文件夹缓存格式：使用 pickle，而非 parquet。
# 原因：parquet 依赖 pyarrow 原生扩展，在部分电脑上（不同 CPU 指令集 / 运行库环境）
# 会在写入、读取时发生原生崩溃，表现为程序静默退出且 Python 无法捕获。
# pickle 只依赖 pandas/numpy（日志解析已验证其在目标机可用），稳定性更好。
CACHE_FILENAME = '_combined_cache.pkl'
LEGACY_CACHE_FILENAME = '_combined_cache.parquet'

def is_compressed_file(filename):
    """判断是否为压缩文件（根据扩展名，不区分大小写）"""
    compressed_exts = ('.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.tgz', '.tbz2', '.txz')
    return filename.lower().endswith(compressed_exts)

def get_file_first_timestamp(filepath):
    """读取文件第一行的时间戳，用于文件排序。返回 datetime 或 None。"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ts_str, _ = parse_timestamp(line)
                if ts_str:
                    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                        try:
                            return datetime.datetime.strptime(ts_str, fmt)
                        except ValueError:
                            continue
                break  # 只读第一行
    except Exception:
        pass
    return None

def convert_folder_to_cache(folder_path, cache_path, progress_callback=None, stop_event=None):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path)
         if os.path.isfile(os.path.join(folder_path, f))
         and f not in (CACHE_FILENAME, LEGACY_CACHE_FILENAME)
         and not is_compressed_file(f)]
    # 按文件第一行时间戳排序，确保多文件拼接顺序正确
    files.sort(key=lambda f: get_file_first_timestamp(f) or datetime.datetime.min)
    total = len(files)
    dfs = []
    for i, fpath in enumerate(files):
        if stop_event and stop_event.is_set():
            return False
        if progress_callback:
            progress_callback(i / total)
        df = load_single_log_file(fpath, stop_event=stop_event)
        if not df.empty:
            dfs.append(df)
    if not dfs:
        return False
    combined = pd.concat(dfs, ignore_index=True)
    # 不按时间戳排序（原始时间戳不可靠），直接按文件顺序分配行号并使用相对时间
    combined['line_no'] = range(1, len(combined)+1)
    # 以第一个原始时间戳为基准，每行 +1ms 生成相对时间
    first_ts = combined['timestamp'].iloc[0] if 'timestamp' in combined.columns and not combined['timestamp'].empty else None
    if first_ts is not None and pd.notna(first_ts):
        base_epoch = first_ts.timestamp()
    else:
        base_epoch = 0.0
    combined['timestamp'] = pd.to_datetime(base_epoch * 1000 + (combined['line_no'] - 1), unit='ms', utc=True)
    log(f"写入缓存: {cache_path} | 行数={len(combined)} | 列数={len(combined.columns)}")
    try:
        combined.to_pickle(cache_path)
    except Exception as e:
        # 缓存写入失败不应中断加载：调用方会回退为直接加载
        log(f"缓存写入失败: {e}")
        return False
    log("缓存写入完成")
    if stop_event and stop_event.is_set():
        return False
    return True

def load_cache(cache_path):
    if not os.path.exists(cache_path):
        return pd.DataFrame()
    return pd.read_pickle(cache_path)

# ...existing code...
def load_single_log_file(filepath, progress_callback=None, stop_event=None):
    """
    逐行解析日志，针对一行可能返回多个片段（如 [ADS]:0 ... 和 [ADS]:1 ...）
    每个解析出的 (ts_str, cols, vals) 都作为单独一行，使用 dict 合并不同列名，
    最终构建 DataFrame，确保不同 model 的 ADS 列都会保留。
    """
    if stop_event and stop_event.is_set():
        return pd.DataFrame()

    # 快速统计总行数（二进制读取，无解码开销）
    total = 0
    try:
        with open(filepath, 'rb') as f:
            for _ in f:
                total += 1
    except Exception:
        return pd.DataFrame()
    if total == 0:
        return pd.DataFrame()

    from collections import defaultdict
    data = defaultdict(list)
    raw_ts_strs = []  # 收集原始时间戳字符串，循环结束后批量转换
    display_time_vals = []  # DISPLAY 格式的 count 值（用作时间轴）
    try:
        f = open(filepath, 'r', encoding='utf-8', errors='ignore')
    except Exception:
        return pd.DataFrame()

    try:
        cached_fmt = None
        cached_variant = None
        # 缓存 ADS regex pattern 避免每行重新编译
        _ads_re = re.compile(r'(\[ADS\]\s*:\s*\d+\s*,[^[]*)')

        for line_count, raw_line in enumerate(f, 1):
            if stop_event and stop_event.is_set():
                f.close()
                return pd.DataFrame()
            line = raw_line.rstrip('\n\r')
            if not line:
                continue

            ts_str, rest = parse_timestamp(line)
            if not rest:
                if ts_str:
                    raw_ts_strs.append(ts_str)
                continue

            # ADS 行：使用原解析逻辑（支持一行多段）
            if '[ADS]' in rest:
                results = parse_log_line(line)
                for ts_str2, cols, vals in results:
                    if cols is None or vals is None:
                        continue
                    if len(cols) != len(vals):
                        continue
                    raw_ts_strs.append(ts_str2 if ts_str2 else None)
                    for c, v in zip(cols, vals):
                        data[c].append(v)
                continue

            # DISPLAY 行：以 count 值为时间轴
            if '[DISPLAY]' in rest:
                count_val, d_cols, d_vals = parse_display_line(rest)
                if count_val is not None and d_cols:
                    display_time_vals.append(count_val)
                    raw_ts_strs.append(None)
                    for c, v in zip(d_cols, d_vals):
                        data[c].append(v)
                continue

            # 非 ADS：格式已知后用缓存避免重复 detect_format
            cols = vals = None
            if config is None:
                continue  # 配置缺失：跳过非 ADS 行（已在启动日志中提示）
            if cached_fmt is not None:
                cols, vals = config.parse_values(cached_fmt, rest, cached_variant)
            if cols is None:
                fmt_name, variant = config.detect_format(rest)
                if fmt_name:
                    cached_fmt = fmt_name
                    cached_variant = variant
                    cols, vals = config.parse_values(fmt_name, rest, variant)

            if cols is not None and vals is not None and len(cols) == len(vals):
                raw_ts_strs.append(ts_str if ts_str else None)
                for c, v in zip(cols, vals):
                    data[c].append(v)

            if progress_callback and total > 0 and line_count % 1000 == 0:
                try:
                    progress_callback(min(line_count / total, 1.0))
                except Exception:
                    pass
    except Exception:
        f.close()
        return pd.DataFrame()
    f.close()

    if not raw_ts_strs:
        return pd.DataFrame()

    # 批量转换时间戳（向量化，比逐行调用快 50-100 倍）
    timestamps = pd.Series(pd.to_datetime(raw_ts_strs, format='%Y-%m-%d %H:%M:%S.%f', errors='coerce'))
    na_mask = timestamps.isna()
    if na_mask.any():
        raw_arr = np.array(raw_ts_strs, dtype=object)
        timestamps.loc[na_mask] = pd.to_datetime(raw_arr[na_mask.values],
                                                  format='%Y-%m-%d %H:%M:%S', errors='coerce').values

    # 列式构建 DataFrame（比 list-of-dicts 快，节省大量 Python 对象开销）
    data['timestamp'] = timestamps
    df = pd.DataFrame(data)

    # DISPLAY 格式：将 count 值存入特殊列，后续在 load_finished 中用作时间轴
    # 仅当长度匹配时才添加（纯 DISPLAY 文件正常；混用文件跳过）
    if display_time_vals and len(display_time_vals) == len(df):
        df['__display_time__'] = display_time_vals

    # 保证 timestamp 在最前并添加 line_no
    cols = list(df.columns)
    cols.remove('timestamp')
    df = df[['timestamp'] + cols]
    df.insert(1, 'line_no', range(1, len(df)+1))

    # 向量化数值类型转换（比逐列循环快）
    numeric_cols = [c for c in df.columns if c not in ('timestamp', 'line_no')]
    if numeric_cols:
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')

    return df
# ...existing code...

class LoadThread(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal(object, bool, str)

    def __init__(self, path, use_cache, force_rebuild, use_relative_time=False, files=None):
        super().__init__()
        self.path = path
        self.use_cache = use_cache
        self.force_rebuild = force_rebuild
        self.use_relative_time = use_relative_time
        self.files = files  # 可选的多文件列表（拖拽使用）
        self._stop = False

    def is_set(self):
        return self._stop

    def stop_load(self):
        self._stop = True

    def _load_folder_direct(self):
        """不使用缓存直接加载文件夹内所有日志，返回 DataFrame（失败返回空表）"""
        files = [os.path.join(self.path, f) for f in os.listdir(self.path)
                 if os.path.isfile(os.path.join(self.path, f))
                 and f not in (CACHE_FILENAME, LEGACY_CACHE_FILENAME)
                 and not is_compressed_file(f)]
        files.sort(key=lambda f: get_file_first_timestamp(f) or datetime.datetime.min)
        total = len(files)
        dfs = []
        for i, fpath in enumerate(files):
            if self._stop:
                return pd.DataFrame()
            self.progress.emit(i / total)
            df = load_single_log_file(fpath, stop_event=self)
            if not df.empty:
                dfs.append(df)
        if not dfs:
            return pd.DataFrame()
        df = pd.concat(dfs, ignore_index=True)
        if 'timestamp' in df.columns and not self.use_relative_time:
            df = df.sort_values('timestamp').reset_index(drop=True)
        df['line_no'] = range(1, len(df) + 1)
        return df

    def run(self):
        try:
            log(f"开始加载 | 路径={self.path} | 多文件={self.files is not None} "
                f"| 缓存={self.use_cache} | 重建={self.force_rebuild}")
            if self.files is not None:
                # 多文件模式：已按时间戳排序
                total = len(self.files)
                dfs = []
                for i, fpath in enumerate(self.files):
                    if self._stop:
                        self.finished.emit(pd.DataFrame(), True, "")
                        return
                    self.progress.emit(i / total)
                    df = load_single_log_file(fpath, stop_event=self)
                    if not df.empty:
                        dfs.append(df)
                if not dfs:
                    df = pd.DataFrame()
                else:
                    df = pd.concat(dfs, ignore_index=True)
                    if 'timestamp' in df.columns and not self.use_relative_time:
                        df = df.sort_values('timestamp').reset_index(drop=True)
                    df['line_no'] = range(1, len(df)+1)
                self.finished.emit(df, self._stop, "")
                return

            if os.path.isfile(self.path):
                def progress_callback(p):
                    self.progress.emit(p)
                df = load_single_log_file(self.path, progress_callback, stop_event=self)
                self.finished.emit(df, self._stop, "")
                return

            if not self.use_cache:
                df = self._load_folder_direct()
                log(f"文件夹直接加载完成 | 行数={len(df)}")
                self.finished.emit(df, self._stop, "")
                return

            cache_path = os.path.join(self.path, CACHE_FILENAME)
            cache_exists = os.path.exists(cache_path)

            if cache_exists and not self.force_rebuild:
                self.progress.emit(0.5)
                log("读取缓存...")
                try:
                    df = load_cache(cache_path)
                except Exception as e:
                    # 缓存文件损坏/版本不兼容：忽略并重建，避免整个加载失败
                    log(f"缓存读取失败，将重建: {e}")
                    df = pd.DataFrame()
                if df is not None and not df.empty:
                    if 'timestamp' in df.columns:
                        # utc=True 确保 timezone 不被剥离，
                        # 否则 _ts_to_epoch 无法区分 naive UTC 和 naive 本地时间
                        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                    log(f"缓存命中 | 行数={len(df)}")
                    self.finished.emit(df, False, "")
                    return
                self.progress.emit(0)

            # 清理历史版本的 parquet 缓存（现已改用 pickle，避免残留旧缓存干扰）
            legacy = os.path.join(self.path, LEGACY_CACHE_FILENAME)
            if os.path.exists(legacy):
                try:
                    os.remove(legacy)
                    log("已删除旧版 parquet 缓存")
                except Exception:
                    pass

            def conv_progress(p):
                self.progress.emit(p)
            success = convert_folder_to_cache(self.path, cache_path, conv_progress, self)
            if self._stop:
                self.finished.emit(pd.DataFrame(), True, "")
                return
            if not success:
                # 缓存写入失败（磁盘不可写等）：回退为直接加载，保证功能可用
                log("缓存构建失败，回退为直接加载（不使用缓存）")
                df = self._load_folder_direct()
                log(f"回退加载完成 | 行数={len(df)}")
                self.finished.emit(df, self._stop, "")
                return
            log("读取新建的缓存...")
            df = load_cache(cache_path)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            log(f"加载完成 | 行数={len(df)} | 列数={len(df.columns)}")
            self.finished.emit(df, False, "")
        except Exception as e:
            log('加载线程异常:\n' + traceback.format_exc())
            self.finished.emit(pd.DataFrame(), False, str(e))

class TimeAxis(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        try:
            if not values:
                return []
            if len(values) > 1:
                diffs = [abs(values[i+1] - values[i]) for i in range(len(values)-1)]
                min_spacing = min(diffs)
            else:
                min_spacing = 1.0
            if min_spacing < 0.1:
                fmt = "%H:%M:%S.%f"
            else:
                fmt = "%H:%M:%S"
            strs = []
            for v in values:
                if np.isnan(v) or v < 0:
                    strs.append("")
                else:
                    try:
                        dt = datetime.datetime.fromtimestamp(v)
                        if fmt == "%H:%M:%S.%f":
                            s = dt.strftime("%H:%M:%S.%f")[:-3]
                        else:
                            s = dt.strftime(fmt)
                        strs.append(s)
                    except (OSError, ValueError):
                        strs.append("")
            return strs
        except Exception as e:
            print(f"TimeAxis error: {e}")
            return [""] * len(values)

# ==================== 支持拖拽的绘图控件 ====================
class LeftPanViewBox(pg.ViewBox):
    """自定义交互：左键拖动=平移，中键拖动=框选放大（RectMode），右键拖动=缩放"""
    def mouseDragEvent(self, ev, axis=None):
        # 仅“左键 + 非坐标轴”走自定义平移，其余交给 pyqtgraph 默认处理：
        # 默认逻辑把左键与中键同等对待，mouseMode=RectMode 时即框选放大
        if ev.button() != Qt.LeftButton or axis is not None:
            super().mouseDragEvent(ev, axis)
            return
        ev.accept()
        # 左键平移：与 PyQtGraph 默认 PanMode 的平移逻辑一致
        mask = np.array(self.state['mouseEnabled'], dtype=np.float64)
        dif = (ev.pos() - ev.lastPos()) * -1
        tr = pg.functions.invertQTransform(self.childGroup.transform())
        tr = tr.map(dif * mask) - tr.map(pg.Point(0, 0))
        x = tr.x() if mask[0] == 1 else None
        y = tr.y() if mask[1] == 1 else None
        self._resetTarget()
        if x is not None or y is not None:
            self.translateBy(x=x, y=y)
        self.sigRangeChangedManually.emit(self.state['mouseEnabled'])

class DropPlotWidget(pg.PlotWidget):
    drop_signal = pyqtSignal(str)

    def __init__(self, parent=None, **kwargs):
        # 必须在 super().__init__() 之前赋值：pyqtgraph 构造过程中就会触发 resizeEvent，
        # 而 PlotWidget 重写了 __getattr__，未定义的属性会直接抛 AttributeError
        self.overlay = None  # 悬浮在右上角的按钮条（跟随/关闭）
        self._overlay_timer = None  # 悬停显隐去抖定时器
        super().__init__(parent, **kwargs)
        self.setAcceptDrops(True)

    def attach_overlay(self, ov):
        """登记右上角悬浮按钮条：默认隐藏，鼠标移到该子视图上时才显示"""
        self.overlay = ov
        ov.hide()
        # 监听本控件、viewport 及按钮条自身/子按钮的进入与离开
        for w in (self, self.viewport(), ov):
            w.installEventFilter(self)
        for btn in ov.findChildren(QPushButton):
            btn.installEventFilter(self)
        self.place_overlay()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Enter, QEvent.Leave):
            self._schedule_overlay_update()
        return super().eventFilter(obj, event)

    def _schedule_overlay_update(self):
        """延后判断显隐：从绘图区移到悬浮按钮的瞬间会有 Leave 事件，需稍等再确认"""
        if self._overlay_timer is None:
            self._overlay_timer = QTimer(self)
            self._overlay_timer.setSingleShot(True)
            self._overlay_timer.setInterval(80)
            self._overlay_timer.timeout.connect(self._update_overlay_visibility)
        self._overlay_timer.start()

    def _update_overlay_visibility(self):
        ov = getattr(self, 'overlay', None)
        if ov is None:
            return
        if self._cursor_inside():
            if not ov.isVisible():
                ov.show()
            self.place_overlay()
        else:
            ov.hide()

    def _cursor_inside(self):
        """鼠标是否位于本子视图内（含悬浮按钮）"""
        w = QApplication.widgetAt(QCursor.pos())
        return w is not None and (w is self or self.isAncestorOf(w))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_overlay()

    def place_overlay(self):
        """把悬浮按钮条贴到绘图区右上角（窗口/分栏尺寸变化时重新定位）"""
        ov = getattr(self, 'overlay', None)
        if ov is None:
            return
        ov.adjustSize()
        ov.move(max(0, self.width() - ov.width() - 8), 6)
        ov.raise_()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        text = event.mimeData().text()
        if text:
            lines = text.strip().split('\n')
            for col in lines:
                if col.strip():
                    self.drop_signal.emit(col.strip())
            event.acceptProposedAction()
        else:
            event.ignore()

class DragTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self._drag_item = None
        self._drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_item = self.itemAt(event.pos())
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_item and self._drag_start_pos:
            delta = (event.pos() - self._drag_start_pos).manhattanLength()
            if delta >= QApplication.startDragDistance():
                texts = []
                # 收集所有已选项（支持 Ctrl 多选拖入）
                for item in self.selectedItems():
                    if item.childCount() > 0:
                        for i in range(item.childCount()):
                            child = item.child(i)
                            data = child.data(0, Qt.UserRole)
                            texts.append(data if data else child.text(0))
                    else:
                        data = item.data(0, Qt.UserRole)
                        texts.append(data if data else item.text(0))
                if not texts:
                    return
                mime = QMimeData()
                mime.setText("\n".join(texts))
                drag = QDrag(self)
                drag.setMimeData(mime)
                drag.exec(Qt.CopyAction)
                self._drag_item = None
                self._drag_start_pos = None
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_item = None
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

# ==================== 绘图子区域 ====================
class PlotSubWidget(QWidget):
    """独立的子绘图区域，包含 PlotWidget 和图例右键移除功能"""
    def __init__(self, main_window, parent_tab, index):
        super().__init__()
        self.main = main_window
        self.parent_tab = parent_tab
        self.index = index
        self.plot_items = {}       # 列名 -> curve
        self.follow_latest = True
        self.view_width = float(self.main.buffer_seconds)
        self.last_update_time = 0
        # 垂直游标状态
        self.cursor_lines = [None, None]  # InfiniteLine 列表 [游标0(红), 游标1(蓝)]
        self.cursor_labels = []
        self.cursor_annotations = {}  # (col, cursor_idx) -> TextItem（标注原地更新）
        self.cursor_time_labels = [None, None]  # 每个游标一个时间标签
        # 鼠标悬浮取值
        self.hover_label = None   # 悬浮提示（坐标值）
        self.hover_dot = None     # 悬浮点标记
        self._cursor_debounce_timer = QTimer()
        self._cursor_debounce_timer.setSingleShot(True)
        self._cursor_debounce_timer.timeout.connect(self.flush_cursor_annotations)
        self._pending_cursor_update = None  # (x, cursor_idx) 待更新的游标数据
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 绘图区域
        self.plot_widget = DropPlotWidget(viewBox=LeftPanViewBox())
        self.plot_widget.setAxisItems({'bottom': TimeAxis(orientation='bottom')})
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '数值')
        self.plot_widget.setLabel('bottom', '时间')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        self.plot_widget.addLegend()
        self.plot_widget.setClipToView(True)
        self.plot_widget.scene().installEventFilter(self)
        # 鼠标悬浮在曲线上时显示该点的横纵坐标值
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.drop_signal.connect(self.add_curve)
        self.plot_widget.installEventFilter(self)
        # 鼠标移出绘图区时结束悬浮显示（enter/leave 事件落在 viewport 上）
        self.plot_widget.viewport().installEventFilter(self)
        self.plot_widget.mouseDoubleClickEvent = self.on_double_click
        self.plot_widget.getViewBox().sigRangeChangedManually.connect(self.on_view_range_changed)

        layout.addWidget(self.plot_widget, stretch=1)

        # 跟随/关闭按钮做成绘图区右上角的悬浮控件，不再单独占一行，
        # 否则每个子图下方都会多出一条约 35px 的空白带
        ctrl_frame = QWidget(self.plot_widget)
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(4)
        self.follow_btn = QPushButton(follow_icon(), "")
        self.follow_btn.setIconSize(QSize(14, 14))
        self.follow_btn.setFixedSize(30, 25)
        self.follow_btn.setProperty("class", "icon")
        self.follow_btn.setToolTip("跟随最新数据（双击绘图区可同步全部子图）")
        self.follow_btn.setAccessibleName("跟随最新数据")
        self.follow_btn.setCheckable(True)
        self.follow_btn.setChecked(self.follow_latest)
        self.follow_btn.clicked.connect(self.toggle_follow)
        ctrl_layout.addWidget(self.follow_btn)
        self.close_btn = QPushButton(close_x_icon(10), "")
        self.close_btn.setIconSize(QSize(10, 10))
        self.close_btn.setFixedSize(25, 25)
        self.close_btn.setProperty("class", "icon")
        self.close_btn.setToolTip("关闭此分栏")
        self.close_btn.setAccessibleName("关闭此分栏")
        self.close_btn.clicked.connect(self.request_close)
        ctrl_layout.addWidget(self.close_btn)

        self.plot_widget.attach_overlay(ctrl_frame)

    def eventFilter(self, obj, event):
        """拦截绘图控件的键盘事件和场景右键事件"""
        # 鼠标移出绘图区：结束悬浮取值显示
        if obj is self.plot_widget.viewport() and event.type() == QEvent.Leave:
            self._hide_hover()
        # 场景级：拦截图例右键（在事件到达任何 item 之前）
        if obj is self.plot_widget.scene():
            if event.type() == QEvent.GraphicsSceneMousePress and event.button() == Qt.RightButton:
                col = self._get_legend_col_at_scene_pos(event.scenePos())
                if col:
                    self._show_diff_menu(col, event.screenPos())
                    return True
        if obj == self.plot_widget and event.type() == QEvent.KeyPress:
            tab = self.parent_tab
            if event.key() == Qt.Key_S:
                tab.sync_x_range_from(self)
                return True
            if any(tab.cursor_enabled):
                if event.key() == Qt.Key_Tab:
                    ci = tab.active_cursor
                    for _ in range(2):
                        ci = (ci + 1) % 2
                        if tab.cursor_enabled[ci]:
                            tab.active_cursor = ci
                            tab._refresh_cursor_styles()
                            break
                    return True
                ci = tab.active_cursor
                if tab.cursor_enabled[ci] and tab.cursor_x[ci] is not None:
                    step = 0.001  # 1ms
                    if event.key() == Qt.Key_Left:
                        tab.cursor_x[ci] -= step
                        tab._sync_cursor_lines_only(tab.cursor_x[ci], cursor_idx=ci)
                        tab._pending_cursor_ci = ci
                        tab._cursor_update_timer.start(60)
                        return True
                    elif event.key() == Qt.Key_Right:
                        tab.cursor_x[ci] += step
                        tab._sync_cursor_lines_only(tab.cursor_x[ci], cursor_idx=ci)
                        tab._pending_cursor_ci = ci
                        tab._cursor_update_timer.start(60)
                        return True
        return super().eventFilter(obj, event)

    def request_close(self):
        self.parent_tab.request_remove_subwidget(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 分栏/窗口尺寸变化后重新对齐左轴，保证各子图网格线垂直对齐
        self.parent_tab._align_left_axes()

    def _get_x_buffer(self, col):
        """从列名提取臂前缀，获取对应 x 轴数据"""
        if ':' not in col:
            return deque()
        prefix = col.split(':', 1)[0]
        return self.main.x_buffers.get(prefix, deque())

    def _compute_diff_data(self, base_col):
        """计算 base_col 的差分序列（相邻采样点差值）。
        新增曲线与实时刷新统一调用本方法，保证前后结果一致：
        - 在线模式：从 x/y 缓冲区按末尾对齐后求差分
        - 离线模式：先剔除 NaN 再对相邻有效采样点求差分（避免 NaN 传播造成漏判）
        - 嵌套差分：基于已有曲线数据再求差分
        返回 (x, dy) 或 None（数据未就绪）。"""
        main = self.main
        # 在线缓冲区
        if base_col in main.y_buffers:
            ybuf = main.y_buffers[base_col]
            xbuf = self._get_x_buffer(base_col)
            if not xbuf:
                return None
            n = min(len(xbuf), len(ybuf))
            if n < 2:
                return None
            y_orig = np.array(ybuf)[-n:]
            x_orig = np.array(xbuf)[-n:]
            return x_orig[1:], np.diff(y_orig)
        # 离线 DataFrame
        if main.df is not None and base_col in main.df.columns:
            y_all = np.asarray(main.df[base_col].values, dtype=float)
            if main.timestamp_epoch is not None and len(main.timestamp_epoch) == len(y_all):
                x_all = main.timestamp_epoch
            elif 'line_no' in main.df.columns:
                x_all = (main.df['line_no'].values - 1) * 0.001
            else:
                x_all = np.arange(len(y_all), dtype=float)
            # 与普通曲线一致：先剔除 NaN，再对相邻有效采样点求差分
            mask = np.isfinite(y_all)
            x_m, y_m = x_all[mask], y_all[mask]
            if len(y_m) < 2:
                return None
            return x_m[1:], np.diff(y_m)
        # 嵌套差分：基于已有曲线数据再求差分
        if base_col in self.plot_items:
            ox, oy = self.plot_items[base_col].getOriginalDataset()
            if ox is None or oy is None:
                return None
            n = min(len(ox), len(oy))
            if n < 2:
                return None
            ox = np.asarray(ox[:n])
            oy = np.asarray(oy[:n])
            return ox[1:], np.diff(oy)
        return None

    def add_curve(self, col):
        if col in self.plot_items:
            return
        is_diff = col.endswith('[diff]')
        # 差分的数据源：仅剥离一层后缀（支持对差分曲线再差分）
        base_col = col[:-6] if is_diff else col

        allow_empty = False  # 在线模式按需记录：允许先创建空曲线，数据到达后自动填充
        if is_diff:
            # 差分曲线：数据源必须存在（在线缓冲区 / 离线数据 / 已有曲线）
            src_ok = (base_col in self.main.y_buffers
                      or (self.main.df is not None and base_col in self.main.df.columns)
                      or base_col in self.plot_items)
            if not src_ok:
                return
            result = self._compute_diff_data(base_col)
            if result is not None:
                x, y = result
            else:
                x, y = np.array([]), np.array([])
                allow_empty = True
        elif col in self.main.y_buffers:
            # 在线模式：与 x 轴按末尾对齐（允许为空）
            y_arr = np.array(self.main.y_buffers[col])
            xbuf = self._get_x_buffer(col)
            x_arr = np.array(xbuf) if xbuf else np.array([])
            n = min(len(x_arr), len(y_arr))
            if n:
                x, y = x_arr[-n:], y_arr[-n:]
            else:
                x, y = np.array([]), np.array([])
                allow_empty = True
        elif self.main.df is not None and col in self.main.df.columns:
            y = self.main.df[col].values
            if self.main.timestamp_epoch is not None:
                x = self.main.timestamp_epoch
            elif 'timestamp' in self.main.df.columns:
                x = _timestamps_to_epoch(self.main.df['timestamp'])
            else:
                x = self.main.df['line_no'].values
            mask = ~np.isnan(y)
            x = x[mask] if len(x) == len(y) else x
            y = y[mask]
        else:
            return

        if not allow_empty and (len(y) == 0 or np.all(np.isnan(y))):
            return

        if is_diff and base_col in self.plot_items:
            # 差分曲线沿用其基曲线的颜色，便于对应识别
            orig_pen = self.plot_items[base_col].opts.get('pen')
            if orig_pen is not None:
                try:
                    color = pg.mkPen(orig_pen).color()
                except Exception:
                    color = self._next_color()
            else:
                color = self._next_color()
        else:
            color = self._next_color()
        pen = pg.mkPen(color=color, width=2.0, style=Qt.DashLine if is_diff else Qt.SolidLine)
        opts = {'pen': pen, 'name': col, 'antialias': False, 'downsample': 300, 'autoDownsample': True}
        if is_diff or col in self.main.y_buffers:
            opts['connect'] = 'finite'  # NaN 处断开，避免误连线造成误判
        curve = self.plot_widget.plot(x, y, **opts)
        self.plot_items[col] = curve
        # 如果游标已激活，为新曲线添加标注
        for ci in range(2):
            if self.parent_tab.cursor_enabled[ci] and self.parent_tab.cursor_x[ci] is not None:
                self.update_cursor_annotations(self.parent_tab.cursor_x[ci], cursor_idx=ci)
        if self.follow_latest and self.main.x_buffers:
            self.scroll_to_latest()
        self.parent_tab._align_left_axes()
        # 在线模式：通知主窗口按需启动该臂的数据记录（仅记录当前操作的臂）
        if hasattr(self.main, '_refresh_recording_targets'):
            self.main._refresh_recording_targets()

    def _get_legend_col_at_scene_pos(self, scene_pos):
        """如果 scene_pos 落在图例标签上，返回对应的 col 名，否则返回 None"""
        legend = self.plot_widget.plotItem.legend
        if legend is None or not legend.scene():
            return None
        legend_rect = legend.mapRectToScene(legend.boundingRect())
        if not legend_rect.contains(scene_pos):
            return None
        for sample, label in legend.items:
            name = label.text
            if isinstance(name, str):
                try:
                    r = label.mapRectToScene(label.boundingRect())
                    if r.contains(scene_pos):
                        return name
                except Exception:
                    continue
        return None

    def _show_diff_menu(self, col, screen_pos):
        """弹出差分/操作菜单"""
        menu = QMenu(self)
        # 差分切换（对所有曲线都可用，含 [diff] 曲线）
        diff_col = f"{col}[diff]"
        if diff_col in self.plot_items:
            action = QAction("隐藏差分", self)
        else:
            action = QAction("显示差分（相邻采样点差值）", self)
        action.triggered.connect(lambda: self._toggle_diff(col))
        menu.addAction(action)
        menu.addSeparator()
        # 删除曲线
        delete_action = QAction("删除曲线", self)
        delete_action.triggered.connect(lambda: self._remove_curve(col))
        menu.addAction(delete_action)
        menu.exec_(screen_pos)

    def _toggle_diff(self, col):
        """切换差分曲线的显示/隐藏"""
        diff_col = f"{col}[diff]"
        if diff_col in self.plot_items:
            self._remove_curve(diff_col)
        else:
            self.add_curve(diff_col)
            if diff_col in self.plot_items:
                try:
                    self.main.statusBar().showMessage(
                        f"已显示 {col} 的差分曲线（相邻采样点差值，虚线显示）")
                except Exception:
                    pass

    def _remove_curve(self, col):
        """从绘图区域移除曲线及其依赖曲线（嵌套差分）"""
        # 先递归移除依赖此曲线的子曲线
        for key in list(self.plot_items.keys()):
            if key.endswith('[diff]') and key[:-6] == col:
                self._remove_curve(key)
        # 再移除自身
        if col in self.plot_items:
            self._safe_remove_item(self.plot_items.pop(col))
        # 在线模式：通知主窗口更新记录目标（该臂无曲线时自动停止记录）
        if hasattr(self.main, '_refresh_recording_targets'):
            self.main._refresh_recording_targets()

    def update_curves(self):
        if not self.main.x_buffers:
            return
        for col, curve in list(self.plot_items.items()):
            if not qt_alive(curve):
                # 曲线底层对象已销毁：清理悬空引用，避免后续访问触发原生崩溃
                del self.plot_items[col]
                continue
            if col.endswith('[diff]'):
                # 差分曲线：与新增时调用同一算法，保证结果前后一致
                # 仅剥离一层后缀：数据源可能是另一条差分曲线（嵌套差分）
                base_col = col[:-6]
                result = self._compute_diff_data(base_col)
                if result is not None:
                    curve.setData(result[0], result[1])
                continue
            if col in self.main.y_buffers:
                # 在线模式：x/y 按末尾对齐（保持同步追加）
                y_arr = np.array(self.main.y_buffers[col])
                xbuf = self._get_x_buffer(col)
                if not xbuf:
                    continue
                x_arr = np.array(xbuf)
                n = min(len(x_arr), len(y_arr))
                if n == 0:
                    continue
                curve.setData(x_arr[-n:], y_arr[-n:])
        if self.follow_latest and self.main.x_buffers:
            self.scroll_to_latest()

    def scroll_to_latest(self):
        if not self.main.x_buffers:
            return
        view_box = self.plot_widget.getViewBox()
        current_range = view_box.viewRange()[0]
        width = current_range[1] - current_range[0]
        if width <= 0 or width > 1e9:
            width = self.view_width
        latest_x = max((xbuf[-1] for xbuf in self.main.x_buffers.values() if len(xbuf) > 0), default=None)
        if latest_x is None:
            return
        view_box.setXRange(latest_x - width, latest_x, padding=0)
        self.view_width = width
        self._auto_range_y()

    def _auto_range_y(self):
        if not self.plot_items:
            return
        view_box = self.plot_widget.getViewBox()
        x_range = view_box.viewRange()[0]
        x_min, x_max = x_range
        y_min = float('inf')
        y_max = -float('inf')
        for col, curve in self.plot_items.items():
            if col in self.main.y_buffers:
                y_full = np.array(self.main.y_buffers[col])
                xbuf = self._get_x_buffer(col)
                if not xbuf:
                    continue
                x_full = np.array(xbuf)
                # 用 min() 对齐长度：注意不能用 [-len(空数组):]，
                # 那等价于 [0:] 会取到全长，导致后面长度不一致而报错
                n = min(len(x_full), len(y_full))
                if n == 0:
                    continue
                x_full = x_full[-n:]
                y_full = y_full[-n:]
                mask = (x_full >= x_min) & (x_full <= x_max) & np.isfinite(y_full)
                if np.any(mask):
                    y_vals = y_full[mask]
                    if len(y_vals) > 0:
                        y_min = min(y_min, np.min(y_vals))
                        y_max = max(y_max, np.max(y_vals))
        if y_min < y_max:
            margin = (y_max - y_min) * 0.05
            view_box.setYRange(y_min - margin, y_max + margin, padding=0)

    def on_view_range_changed(self, view_box):
        self.follow_latest = False
        self.follow_btn.setChecked(False)

    def on_double_click(self, event):
        # 双击时通知父标签页同步所有子图
        self.parent_tab.sync_scroll_to_latest(source_width=self.view_width)

    def toggle_follow(self, checked):
        self.follow_latest = checked
        if checked and self.main.x_buffers:
            self.scroll_to_latest()

    def _next_color(self):
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        idx = len(self.plot_items) % len(colors)
        return colors[idx]

    # ==================== 垂直游标 ====================
    CURSOR_COLORS = ['r', 'b']

    def set_cursor_visible(self, x, enabled, cursor_idx=0):
        """显示或隐藏垂直游标线"""
        if enabled:
            if self.cursor_lines[cursor_idx] is None:
                color = self.CURSOR_COLORS[cursor_idx]
                line = pg.InfiniteLine(
                    angle=90, movable=True,
                    pen=pg.mkPen(color, width=2.0, style=Qt.SolidLine))
                line.sigDragged.connect(lambda l, i=cursor_idx: self._on_cursor_dragged(l, i))
                line.sigPositionChangeFinished.connect(
                    lambda l, i=cursor_idx: self._on_cursor_drag_finished(l, i))
                self.cursor_lines[cursor_idx] = line
            self.cursor_lines[cursor_idx].setPos(x)
            # 确保 ViewBox 有有效范围，防止 InfiniteLine 导致 NaN
            vb = self.plot_widget.getViewBox()
            xr, yr = vb.viewRange()
            if not np.isfinite(yr[0]) or not np.isfinite(yr[1]) or yr[0] >= yr[1]:
                vb.setYRange(-1, 1)
            if not np.isfinite(xr[0]) or not np.isfinite(xr[1]) or xr[0] >= xr[1]:
                vb.setXRange(x - 1, x + 1)
            self.plot_widget.addItem(self.cursor_lines[cursor_idx])
            self.update_cursor_annotations(x, cursor_idx)
            self._add_cursor_time_label(x, cursor_idx)
        else:
            self._remove_cursor_labels()
            if self.cursor_lines[cursor_idx] is not None:
                self.plot_widget.removeItem(self.cursor_lines[cursor_idx])
                self.cursor_lines[cursor_idx] = None

    def _on_cursor_dragged(self, line, cursor_idx):
        """拖拽中同步线条位置（不更新标注），并设为活动游标"""
        self.parent_tab.active_cursor = cursor_idx
        self.parent_tab._refresh_cursor_styles()
        x = line.value()
        self.parent_tab.sync_cursor_lines(x, source_sub=self, cursor_idx=cursor_idx)

    def _on_cursor_drag_finished(self, line, cursor_idx):
        """拖拽结束后更新所有标注"""
        x = line.value()
        self.parent_tab.sync_cursor_annotations(x, cursor_idx=cursor_idx)

    def flush_cursor_annotations(self):
        """定时器去抖刷新，处理最后一个待更新的游标位置"""
        if self._pending_cursor_update is not None:
            x, cursor_idx = self._pending_cursor_update
            self._pending_cursor_update = None
            self.update_cursor_annotations(x, cursor_idx)

    def update_cursor_annotations(self, x, cursor_idx=0):
        """创建/更新游标与曲线交点的数值标注（原地更新，避免反复创建删除标签）"""
        self._add_cursor_time_label(x, cursor_idx)
        if not self.plot_items:
            return

        view_box = self.plot_widget.getViewBox()
        x_range = view_box.viewRange()[0]
        y_range = view_box.viewRange()[1]
        x_width = x_range[1] - x_range[0]
        y_height = y_range[1] - y_range[0]
        x_offset = x_width * 0.01 if x_width > 0 else 0.01

        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        # 第一遍：收集所有曲线的 Y 值
        candidates = []  # (y_val, col, idx, color)
        for idx, (col, curve) in enumerate(self.plot_items.items()):
            y_val = None
            if col in self.main.y_buffers:
                y_arr = np.array(self.main.y_buffers[col])
                xbuf = self._get_x_buffer(col)
                x_arr = np.array(xbuf) if xbuf else np.array([])
                # 同 _auto_range_y：空数组不能用 [-len():] 截取，否则会取到全长
                n = min(len(x_arr), len(y_arr))
                if n > 0:
                    x_arr = x_arr[-n:]
                    y_arr = y_arr[-n:]
                    i = np.clip(np.searchsorted(x_arr, x), 0, n - 1)
                    if i > 0 and abs(x_arr[i-1] - x) < abs(x_arr[i] - x):
                        i = i - 1
                    y_val = y_arr[i]
            elif self.main.df is not None and col in self.main.df.columns:
                if self.main.timestamp_epoch is not None:
                    x_arr = self.main.timestamp_epoch
                elif 'timestamp' in self.main.df.columns:
                    x_arr = _timestamps_to_epoch(self.main.df['timestamp'])
                else:
                    x_arr = self.main.df['line_no'].values
                y_arr = self.main.df[col].values
                mask = ~np.isnan(y_arr)
                if len(x_arr) == len(y_arr):
                    x_arr = x_arr[mask]
                    y_arr = y_arr[mask]
                if len(y_arr) > 0:
                    i = np.clip(np.searchsorted(x_arr, x), 0, len(x_arr)-1)
                    if i > 0 and abs(x_arr[i-1] - x) < abs(x_arr[i] - x):
                        i = i - 1
                    y_val = y_arr[i]

            if y_val is None or (isinstance(y_val, float) and np.isnan(y_val)):
                continue
            candidates.append((y_val, col, idx, colors[idx % len(colors)]))

        if not candidates:
            stale_keys = list(self.cursor_annotations.keys())
            for key in stale_keys:
                self.plot_widget.removeItem(self.cursor_annotations.pop(key))
            return

        # 按 Y 值排序，分组处理重合标注
        candidates.sort(key=lambda t: t[0])
        y_threshold = y_height * 0.03 if y_height > 0 else 0.1

        # 将相近 Y 值的曲线分成一组，垂直错开避免遮挡
        groups = []
        cur_group = [candidates[0]]
        for i in range(1, len(candidates)):
            if abs(candidates[i][0] - cur_group[-1][0]) < y_threshold:
                cur_group.append(candidates[i])
            else:
                groups.append(cur_group)
                cur_group = [candidates[i]]
        groups.append(cur_group)

        active_keys = set()
        for group in groups:
            n = len(group)
            if n == 1:
                y_val, col, idx, color = group[0]
                key = (col, cursor_idx)
                active_keys.add(key)
                text = f"{col}={y_val:.5f}"
                if key in self.cursor_annotations:
                    label = self.cursor_annotations[key]
                    label.setText(text)
                    label.setColor(color)
                    label.setPos(x + x_offset, y_val)
                else:
                    label = pg.TextItem(text=text, anchor=(0, 1.3), color=color)
                    label.setPos(x + x_offset, y_val)
                    self.plot_widget.addItem(label)
                    self.cursor_annotations[key] = label
            else:
                # 多条曲线 Y 值接近，垂直错开显示
                spacing = y_threshold * 0.7
                mid = (n - 1) / 2
                for i, (y_val, col, idx, color) in enumerate(group):
                    y_offset = (i - mid) * spacing
                    key = (col, cursor_idx)
                    active_keys.add(key)
                    text = f"{col}={y_val:.5f}"
                    if key in self.cursor_annotations:
                        label = self.cursor_annotations[key]
                        label.setText(text)
                        label.setColor(color)
                        label.setPos(x + x_offset, y_val + y_offset)
                    else:
                        label = pg.TextItem(text=text, anchor=(0, 1.3), color=color)
                        label.setPos(x + x_offset, y_val + y_offset)
                        self.plot_widget.addItem(label)
                        self.cursor_annotations[key] = label

        # 清理已删除曲线的标注
        stale_keys = [k for k in list(self.cursor_annotations) if k[1] == cursor_idx and k not in active_keys]
        for key in stale_keys:
            self.plot_widget.removeItem(self.cursor_annotations.pop(key))

    def _remove_cursor_labels(self):
        """移除所有数值标注和时间标注（跳过已销毁的悬空引用）"""
        for label in self.cursor_annotations.values():
            self._safe_remove_item(label)
        self.cursor_annotations.clear()
        for ci in range(2):
            if self.cursor_time_labels[ci] is not None:
                self._safe_remove_item(self.cursor_time_labels[ci])
                self.cursor_time_labels[ci] = None
        for label in self.cursor_labels:
            self._safe_remove_item(label)
        self.cursor_labels.clear()

    def _safe_remove_item(self, item):
        """安全移除绘图项：底层 C++ 对象已销毁时跳过。

        PyQt 的 Python 包装对象可能比底层 C++ 对象存活更久，此时对其调用
        removeItem 会触发 access violation（原生崩溃，Python 无法捕获）。
        """
        if not qt_alive(item) or not qt_alive(self.plot_widget):
            return
        try:
            self.plot_widget.removeItem(item)
        except Exception:
            pass

    def _add_cursor_time_label(self, x, cursor_idx=0):
        """在游标线左侧添加/更新时间标注（原地更新）"""
        try:
            dt = datetime.datetime.fromtimestamp(x)
            time_str = dt.strftime("%H:%M:%S.%f")[:-3]
        except Exception:
            time_str = f"{x:.3f}"
        view_box = self.plot_widget.getViewBox()
        y_range = view_box.viewRange()[1]
        y_center = (y_range[0] + y_range[1]) / 2
        color = self.CURSOR_COLORS[cursor_idx]
        if self.cursor_time_labels[cursor_idx] is not None:
            label = self.cursor_time_labels[cursor_idx]
            label.setText(f"{time_str}")
            label.setPos(x, y_center)
        else:
            label = pg.TextItem(text=f"{time_str}", anchor=(1, 0.5), color=color)
            label.setPos(x, y_center)
            self.plot_widget.addItem(label)
            self.cursor_time_labels[cursor_idx] = label

    # ==================== 鼠标悬浮取值 ====================
    HOVER_PICK_RADIUS_PX = 12.0   # 距曲线多少像素内才算“悬浮在曲线上”

    def _format_x_value(self, x, col):
        """按当前数据源格式化横坐标：有时间轴时显示时刻，否则显示行号"""
        main = self.main
        base_col = col
        while base_col.endswith('[diff]'):
            base_col = base_col[:-6]
        # 在线模式的 x 是 epoch 秒；离线则取决于是否解析出时间戳
        is_time = base_col in main.y_buffers or main.timestamp_epoch is not None
        if not is_time:
            return f"行 {int(round(x))}"
        try:
            return datetime.datetime.fromtimestamp(x).strftime("%H:%M:%S.%f")[:-3]
        except Exception:
            return f"{x:.3f}"

    def _curve_color(self, curve):
        """取曲线当前颜色，用于悬浮标记点与文字"""
        try:
            pen = curve.opts.get('pen')
            if pen is not None:
                return pg.mkPen(pen).color()
        except Exception:
            pass
        return QColor('#1f77b4')

    def _on_mouse_moved(self, pos):
        """鼠标移动：找出拾取半径内的所有曲线，显示各自 (x, y)。

        两条曲线重合时两条都会列出（按各自颜色区分），而不是只显示其中一条。
        """
        try:
            if not self.plot_items or not qt_alive(self.plot_widget):
                self._hide_hover()
                return
            vb = self.plot_widget.getViewBox()
            if not self.plot_widget.sceneBoundingRect().contains(pos):
                self._hide_hover()
                return
            mp = vb.mapSceneToView(pos)
            mx, my = mp.x(), mp.y()
            xr, yr = vb.viewRange()
            if xr[1] <= xr[0] or yr[1] <= yr[0]:
                self._hide_hover()
                return
            # 视坐标 -> 屏幕像素 的缩放，用于按像素判定“贴住曲线”
            rect = vb.boundingRect()
            sx = rect.width() / (xr[1] - xr[0])
            sy = rect.height() / (yr[1] - yr[0])
            radius = self.HOVER_PICK_RADIUS_PX

            cands = []   # (像素距离, 列名, x, y, 颜色)
            for col, curve in self.plot_items.items():
                if not qt_alive(curve):
                    continue
                try:
                    x_arr, y_arr = curve.getOriginalDataset()
                except Exception:
                    continue
                if x_arr is None or y_arr is None:
                    continue
                n = len(y_arr)
                if n == 0 or len(x_arr) != n:
                    continue
                i = int(np.searchsorted(x_arr, mx))
                i = max(0, min(n - 1, i))
                # 该曲线在最近点附近的有效点里取离鼠标最近的一个（跳过 NaN 断点）
                local = None
                for j in range(max(0, i - 5), min(n - 1, i + 5) + 1):
                    yv = y_arr[j]
                    if not np.isfinite(yv):
                        continue
                    d = np.hypot((x_arr[j] - mx) * sx, (yv - my) * sy)
                    if local is None or d < local[0]:
                        local = (d, float(x_arr[j]), float(yv))
                if local is not None and local[0] <= radius:
                    cands.append((local[0], col, local[1], local[2], self._curve_color(curve)))

            if not cands:
                self._hide_hover()
                return
            cands.sort(key=lambda t: t[3], reverse=True)   # 按 Y 从高到低排列，便于阅读
            self._show_hover(cands)
        except Exception:
            # 高频回调，任何异常都静默处理，避免弹窗风暴
            pass

    def _show_hover(self, cands):
        """显示/更新悬浮提示与标记点（原地复用，避免反复创建销毁绘图项）

        cands: [(像素距离, 列名, x, y, 颜色), ...]，可能包含多条重合曲线
        """
        if self.hover_label is None or not qt_alive(self.hover_label):
            label = pg.TextItem(anchor=(0, 1.15), fill=pg.mkBrush(255, 255, 255, 235),
                                border=pg.mkPen('#CBD5E1'))
            label.setZValue(1e9)
            self.plot_widget.addItem(label)
            self.hover_label = label
        if self.hover_dot is None or not qt_alive(self.hover_dot):
            dot = pg.ScatterPlotItem(symbol='o', size=9, pen=pg.mkPen('#FFFFFF', width=1.5))
            dot.setZValue(1e9)
            self.plot_widget.addItem(dot)
            self.hover_dot = dot

        # 时间取离鼠标最近（像素距离最小）的那条曲线
        _, near_col, near_x, _, _ = min(cands, key=lambda t: t[0])
        rows = [f'<div style="color:#1E293B">{self._format_x_value(near_x, near_col)}</div>']
        spots = []
        for d, col, x, y, color in cands:
            name = col.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            rows.append(f'<div style="color:{color.name()}">{name} = {y:.5f}</div>')
            spots.append({'pos': (x, y), 'brush': pg.mkBrush(color),
                          'pen': pg.mkPen('#FFFFFF', width=1.5), 'size': 9})

        self.hover_label.setHtml(''.join(rows))
        # 锚点放在最高的那个点上，避免提示框压住曲线
        self.hover_label.setPos(cands[0][2], cands[0][3])
        self.hover_label.setVisible(True)
        self.hover_dot.setData(spots)
        self.hover_dot.setVisible(True)

    def _hide_hover(self):
        for item in (self.hover_label, self.hover_dot):
            if item is not None and qt_alive(item):
                try:
                    if item.isVisible():
                        item.setVisible(False)
                except Exception:
                    pass

    def clear_all_curves(self):
        self._hide_hover()
        self._remove_cursor_labels()
        for curve in self.plot_items.values():
            self._safe_remove_item(curve)
        self.plot_items.clear()
        # 在线模式：曲线全部清除后停止所有臂的记录
        if hasattr(self.main, '_refresh_recording_targets'):
            self.main._refresh_recording_targets()

class PlotTab(QWidget):
    def __init__(self, main_window, tab_name="Tab"):
        super().__init__()
        self.main = main_window
        self.tab_name = tab_name
        self.splitter = None
        self.sub_widgets = []
        self.last_update_time = 0
        # 垂直游标状态（跨子图统一）
        self.cursor_enabled = [False, False]  # [游标0, 游标1]
        self.cursor_x = [None, None]
        self.active_cursor = 0
        self._align_pending = False
        self._cursor_update_timer = QTimer()
        self._cursor_update_timer.setSingleShot(True)
        self._cursor_update_timer.timeout.connect(self._flush_cursor_update)
        self._pending_cursor_ci = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setFocusPolicy(Qt.StrongFocus)

        self.splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(self.splitter, stretch=1)

        self._add_sub_widget()

    def _add_sub_widget(self):
        sub = PlotSubWidget(self.main, self, len(self.sub_widgets))
        self.sub_widgets.append(sub)
        self.splitter.addWidget(sub)
        # 如果游标已激活，新子图也显示游标
        for ci in range(2):
            if self.cursor_enabled[ci] and self.cursor_x[ci] is not None:
                sub.set_cursor_visible(self.cursor_x[ci], True, cursor_idx=ci)
        self._update_bottom_labels()
        self._align_left_axes()

    def _update_bottom_labels(self):
        """纵向堆叠子图时，仅最下方子图保留"时间"轴标签，其余收起。

        每张子图都画一遍"时间"会白白多占约 18px 高度，堆叠时留白明显。
        """
        vertical = self.splitter.orientation() == Qt.Vertical
        n = len(self.sub_widgets)
        for i, sub in enumerate(self.sub_widgets):
            axis = sub.plot_widget.getAxis('bottom')
            show = (not vertical) or (i == n - 1)
            if show:
                axis.setLabel('时间')
            if hasattr(axis, 'showLabel'):
                axis.showLabel(show)

    def split_horizontal(self):
        if not self.sub_widgets:
            return
        if self.splitter.orientation() == Qt.Vertical:
            self.splitter.setOrientation(Qt.Horizontal)
        self._add_sub_widget()

    def split_vertical(self):
        if not self.sub_widgets:
            return
        if self.splitter.orientation() == Qt.Horizontal:
            self.splitter.setOrientation(Qt.Vertical)
        self._add_sub_widget()

    def request_remove_subwidget(self, sub_widget):
        if len(self.sub_widgets) <= 1:
            QMessageBox.information(None, "提示", "至少需要保留一个子图")
            return
        # 先清除该子图内的曲线与游标项，确保销毁前绘图场景中不残留引用，
        # 否则底层图形对象被销毁后仍被场景/字典引用，绘制时会触发原生崩溃
        try:
            if qt_alive(sub_widget):
                sub_widget.clear_all_curves()
        except Exception:
            pass
        if sub_widget in self.sub_widgets:
            self.sub_widgets.remove(sub_widget)
        # 直接使用对象引用销毁，避免依赖索引（索引一旦错位会误删其他分栏）
        if qt_alive(sub_widget):
            sub_widget.setParent(None)
            sub_widget.deleteLater()
        # 删除后"最下方子图"可能变化，需重新分配"时间"轴标签
        self._update_bottom_labels()
        # 在线模式：分栏关闭后其曲线不再参与记录目标计算
        if hasattr(self.main, '_refresh_recording_targets'):
            self.main._refresh_recording_targets()

    def sync_scroll_to_latest(self, source_width=None):
        """同步所有子图的 X 轴到最新数据点，并开启跟随"""
        if not self.sub_widgets:
            return
        # 确定使用的 X 轴跨度宽度：如果提供了 source_width 则使用，否则取所有子图宽度的最大值
        if source_width is not None and source_width > 0:
            width = source_width
        else:
            widths = [sub.view_width for sub in self.sub_widgets if sub.view_width > 0]
            width = max(widths) if widths else float(self.main.buffer_seconds)
        # 遍历所有子图，设置跟随并滚动到最新
        for sub in self.sub_widgets:
            sub.follow_latest = True
            sub.follow_btn.setChecked(True)
            sub.view_width = width
            sub.scroll_to_latest()
        QTimer.singleShot(100, self._align_left_axes)

    def clear_all_curves(self):
        for sub in self.sub_widgets:
            sub.clear_all_curves()
        QTimer.singleShot(100, self._align_left_axes)

    def update_curves(self):
        now = datetime.datetime.now().timestamp() * 1000
        if now - self.last_update_time < 50:
            return
        self.last_update_time = now
        for sub in self.sub_widgets:
            sub.update_curves()

    # ==================== 垂直游标控制 ====================

    def toggle_cursor(self, cursor_idx=0):
        """切换统一垂直游标的显示/隐藏"""
        self.cursor_enabled[cursor_idx] = not self.cursor_enabled[cursor_idx]
        if self.cursor_enabled[cursor_idx]:
            if not self.sub_widgets:
                self.cursor_enabled[cursor_idx] = False
                return
            # 初始位置：第一个子图可见 X 范围的中心
            vb = self.sub_widgets[0].plot_widget.getViewBox()
            x_range = vb.viewRange()[0]
            if x_range[0] < x_range[1]:
                self.cursor_x[cursor_idx] = (x_range[0] + x_range[1]) / 2.0
            else:
                self.cursor_x[cursor_idx] = x_range[0]
            self.active_cursor = cursor_idx
            for sub in self.sub_widgets:
                sub.set_cursor_visible(self.cursor_x[cursor_idx], True, cursor_idx=cursor_idx)
            self._refresh_cursor_styles()
            self.setFocus()
        else:
            self.cursor_x[cursor_idx] = None
            for sub in self.sub_widgets:
                sub.set_cursor_visible(0, False, cursor_idx=cursor_idx)

    def sync_cursor_lines(self, x, source_sub=None, cursor_idx=0):
        """同步所有子图的游标线位置（拖拽中调用）"""
        if not self.cursor_enabled[cursor_idx]:
            return
        self.cursor_x[cursor_idx] = x
        for sub in self.sub_widgets:
            if sub is source_sub or sub.cursor_lines[cursor_idx] is None:
                continue
            sub.cursor_lines[cursor_idx].blockSignals(True)
            sub.cursor_lines[cursor_idx].setPos(x)
            sub.cursor_lines[cursor_idx].blockSignals(False)

    def sync_cursor_annotations(self, x, cursor_idx=0):
        """更新所有子图的交点标注（拖拽结束后调用）"""
        if not self.cursor_enabled[cursor_idx]:
            return
        self.cursor_x[cursor_idx] = x
        for sub in self.sub_widgets:
            sub.update_cursor_annotations(x, cursor_idx=cursor_idx)

    def _sync_cursor_lines_only(self, x, cursor_idx=0):
        """仅同步游标线位置，不更新标注（用于键盘去抖）"""
        if not self.cursor_enabled[cursor_idx]:
            return
        self.cursor_x[cursor_idx] = x
        for sub in self.sub_widgets:
            if sub.cursor_lines[cursor_idx] is not None:
                sub.cursor_lines[cursor_idx].blockSignals(True)
                sub.cursor_lines[cursor_idx].setPos(x)
                sub.cursor_lines[cursor_idx].blockSignals(False)

    def _refresh_cursor_styles(self):
        """刷新游标样式：活动游标实线，非活动游标虚线"""
        for sub in self.sub_widgets:
            for ci in range(2):
                line = sub.cursor_lines[ci]
                if line is not None:
                    color = sub.CURSOR_COLORS[ci]
                    if ci == self.active_cursor:
                        line.setPen(pg.mkPen(color, width=2.0, style=Qt.SolidLine))
                    else:
                        line.setPen(pg.mkPen(color, width=1.5, style=Qt.DashLine))

    def _update_cursor_position(self):
        """键盘移动游标后更新所有子图的线条和标注（标注去抖）"""
        ci = self.active_cursor
        if not self.cursor_enabled[ci] or self.cursor_x[ci] is None:
            return
        # 立即同步线条位置
        for sub in self.sub_widgets:
            if sub.cursor_lines[ci] is not None:
                sub.cursor_lines[ci].blockSignals(True)
                sub.cursor_lines[ci].setPos(self.cursor_x[ci])
                sub.cursor_lines[ci].blockSignals(False)
        # 标注延迟去抖更新（快速按键只刷新最后一次）
        self._pending_cursor_ci = ci
        self._cursor_update_timer.start(60)

    def _flush_cursor_update(self):
        """去抖定时器触发，更新所有子图的游标标注"""
        ci = self._pending_cursor_ci
        self._pending_cursor_ci = None
        if ci is None or not self.cursor_enabled[ci] or self.cursor_x[ci] is None:
            return
        for sub in self.sub_widgets:
            sub.update_cursor_annotations(self.cursor_x[ci], cursor_idx=ci)

    def jump_to_time(self, time_str):
        """输入时间字符串，将活动游标跳转到最近的数据位置

        支持格式: HH:MM, HH:MM:SS, HH:MM:SS.fff
        """
        ci = self.active_cursor
        time_str = time_str.strip()
        # 解析时间字符串
        if time_str.count(':') == 1:
            time_str += ':00'
        elif time_str.count(':') != 2:
            QMessageBox.warning(self.main, "输入错误", "时间格式无效，请使用 HH:MM 或 HH:MM:SS 或 HH:MM:SS.fff")
            return
        try:
            if '.' in time_str:
                t = datetime.datetime.strptime(time_str, '%H:%M:%S.%f').time()
            else:
                t = datetime.datetime.strptime(time_str, '%H:%M:%S').time()
        except ValueError:
            QMessageBox.warning(self.main, "输入错误", f"无法解析时间: {time_str}")
            return

        # 获取可用的 X 轴数据
        x_vals = None
        is_online = bool(self.main.x_buffers)

        if is_online:
            # 在线模式：收集所有臂的 x 值
            all_x = []
            for buf in self.main.x_buffers.values():
                all_x.extend(buf)
            if not all_x:
                QMessageBox.information(self.main, "提示", "在线模式还没有数据")
                return
            x_vals = np.array(all_x)
        elif self.main.timestamp_epoch is not None and len(self.main.timestamp_epoch) > 0:
            x_vals = self.main.timestamp_epoch
        else:
            QMessageBox.information(self.main, "提示", "没有可用的数据")
            return

        # 从数据中取中间点的日期作为基准
        mid_x = x_vals[len(x_vals) // 2]
        try:
            base_date = datetime.datetime.fromtimestamp(mid_x).date()
        except (OSError, OverflowError, ValueError):
            base_date = datetime.date.today()

        # 构建目标 datetime 并转 epoch
        target_dt = datetime.datetime.combine(base_date, t)
        target_epoch = target_dt.timestamp()

        # 尝试 target_epoch 和前一天/后一天，取最接近的
        candidates = [target_epoch, target_epoch - 86400, target_epoch + 86400]
        best_epoch = None
        best_dist = float('inf')
        for cand in candidates:
            idx = np.searchsorted(x_vals, cand)
            for i in (idx - 1, idx):
                if 0 <= i < len(x_vals):
                    dist = abs(x_vals[i] - cand)
                    if dist < best_dist:
                        best_dist = dist
                        best_epoch = x_vals[i]

        if best_epoch is None:
            QMessageBox.information(self.main, "提示", "未找到匹配的时间位置")
            return

        # 确保游标已启用
        if not self.cursor_enabled[ci]:
            self.toggle_cursor(cursor_idx=ci)

        if not self.cursor_enabled[ci]:
            return  # 启用失败

        # 设置游标位置
        self.cursor_x[ci] = best_epoch
        for sub in self.sub_widgets:
            if sub.cursor_lines[ci] is not None:
                sub.cursor_lines[ci].blockSignals(True)
                sub.cursor_lines[ci].setPos(best_epoch)
                sub.cursor_lines[ci].blockSignals(False)
            sub.update_cursor_annotations(best_epoch, cursor_idx=ci)

        # 如果游标不在当前视野内，滚动视图使游标可见
        if np.isfinite(best_epoch):
            vb = self.sub_widgets[0].plot_widget.getViewBox()
            x_range = vb.viewRange()[0]
            if (np.isfinite(x_range[0]) and np.isfinite(x_range[1])
                    and (best_epoch < x_range[0] or best_epoch > x_range[1])):
                margin = (x_range[1] - x_range[0]) * 0.2
                if margin > 0:
                    vb.setXRange(best_epoch - margin, best_epoch + margin, padding=0)

    def _align_left_axes(self):
        """对齐所有子视图的左轴宽度（去抖，多次快速调整只执行一次）"""
        if len(self.sub_widgets) < 2:
            return
        if self._align_pending:
            return
        self._align_pending = True
        QTimer.singleShot(0, self._do_align_left_axes)

    def _do_align_left_axes(self):
        """实际执行左轴对齐"""
        self._align_pending = False
        if len(self.sub_widgets) < 2:
            return
        for sub in self.sub_widgets:
            sub.plot_widget.getAxis('left').setWidth(None)
        QApplication.processEvents()
        max_w = 0
        for sub in self.sub_widgets:
            w = sub.plot_widget.getAxis('left').width()
            if w > max_w:
                max_w = w
        if max_w > 0:
            for sub in self.sub_widgets:
                sub.plot_widget.getAxis('left').setWidth(max_w + 4)

    def sync_x_range_from(self, source_sub):
        """将 source_sub 的 X 轴范围同步到所有子视图"""
        vb = source_sub.plot_widget.getViewBox()
        x_range = vb.viewRange()[0]
        if x_range[0] >= x_range[1]:
            return
        for sub in self.sub_widgets:
            if sub is source_sub:
                continue
            sub.follow_latest = False
            sub.follow_btn.setChecked(False)
            sub.plot_widget.getViewBox().setXRange(x_range[0], x_range[1], padding=0)
        QTimer.singleShot(100, self._align_left_axes)

    def keyPressEvent(self, event):
        """T同步时间轴缩放，左右箭头移动游标（1ms步进），Tab切换当前操作游标"""
        if event.key() == Qt.Key_T and self.sub_widgets:
            self.sync_x_range_from(self.sub_widgets[0])
            return
        ci = self.active_cursor
        if any(self.cursor_enabled):
            if event.key() == Qt.Key_Tab:
                # 切换到下一个已启用的游标
                for _ in range(2):
                    ci = (ci + 1) % 2
                    if self.cursor_enabled[ci]:
                        self.active_cursor = ci
                        self._refresh_cursor_styles()
                        break
                return
            if self.cursor_enabled[ci] and self.cursor_x[ci] is not None:
                step = 0.001  # 1ms
                if event.key() == Qt.Key_Left:
                    self.cursor_x[ci] -= step
                    self._update_cursor_position()
                    return
                elif event.key() == Qt.Key_Right:
                    self.cursor_x[ci] += step
                    self._update_cursor_position()
                    return
        super().keyPressEvent(event)

# ==================== 时间戳换算（向量化） ====================
def _wall_clock_to_epoch(values):
    """把"墙上时间"(naive) 按本地时区解释为 Unix epoch，整批一次算完。

    与 Python datetime.timestamp() 处理 naive 时间的行为一致，但避免了逐行调用：
    逐行 to_pydatetime().timestamp() 在数十万行时既非常慢（数万次 Python 调用
    与 CRT 时间转换），也是原生崩溃的高发点。
    说明：本地偏移按当前时刻取一次，跨越夏令时切换的日志会有 1 小时偏差。
    """
    arr = np.asarray(values, dtype='datetime64[ns]')
    offset = datetime.datetime.now().astimezone().utcoffset()
    offset_s = offset.total_seconds() if offset is not None else 0.0
    mask = np.isnat(arr)
    epoch = arr.astype('int64').astype('float64') / 1e9 - offset_s
    if mask.any():
        epoch[mask] = np.nan
    return epoch


def _timestamps_to_epoch(ts_series):
    """时间戳列 → epoch 数组（向量化）。带时区时先剥掉时区、保留墙上时间。"""
    ts = pd.Series(pd.to_datetime(ts_series, errors='coerce'))
    if getattr(ts.dtype, 'tz', None) is not None:
        ts = ts.dt.tz_localize(None)
    return _wall_clock_to_epoch(ts.to_numpy())


def _first_timestamp_epoch(ts_series):
    """只转换第一个有效时间戳（相对时间模式仅需一个基准值）

    复用向量化实现，避免 datetime.timestamp() 在 1970 年之前会抛
    OSError（Errno 22）的问题。
    """
    first = pd.Series(pd.to_datetime(ts_series, errors='coerce')).dropna()
    if len(first) == 0:
        return None
    val = float(_timestamps_to_epoch(first.iloc[:1])[0])
    return None if np.isnan(val) else val


# ==================== 主窗口 ====================
# 屏幕切换事件类型（窗口拖至副屏/DPI 变化时触发界面刷新）
_SCREEN_CHANGE_TYPE = getattr(QEvent, 'ScreenChangeInternal', None)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 设置窗口初始大小：宽度为屏幕宽度的 70%，高度为屏幕高度的 80%
        # 获取屏幕可用尺寸（排除任务栏）
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        # 设置窗口初始大小：宽度为屏幕宽度的 70%，高度为屏幕高度的 80%
        win_width = max(int(screen_width * 0.7), 1000)
        win_height = max(int(screen_height * 0.8), 800)
        # 不超过屏幕可用区域，避免低分辨率/小屏下窗口被截断
        win_width = min(win_width, screen_width)
        win_height = min(win_height, screen_height)

        self.resize(win_width, win_height)
        self.setMinimumSize(min(1000, screen_width), min(800, screen_height))   # 允许用户手动缩小但不能小于此尺寸
        self.setWindowTitle("YC日志分析平台")
        self.setAcceptDrops(True)
        self.df = None
        self.current_columns = []
        self.load_thread = None
        self._dropped_files = None  # 拖入的多文件列表（path_edit 无法表示时使用）
        self.live_threads = []
        self.use_cache = True
        self.force_rebuild = False
        self.timestamp_epoch = None

        self.buffer_seconds = 40
        self.buffer_points = self.buffer_seconds * 1000
        self.buffer_size = self.buffer_points
        self.x_buffers = {}  # arm_prefix → deque(epoch)
        self.y_buffers = {}
        self._tree_prebuilt = False
        # ---- 在线按需记录状态 ----
        self._arm_active_cols = {}    # 臂前缀 → 该臂当前已绘制列（裸列名）集合
        self._live_conn = None        # 最近一次在线连接参数（用于按臂重启线程）
        self._last_time_jump_text = ""  # 记录上一次输入的时间，弹窗时回填
        self.update_timer = QTimer()
        self.update_timer.setInterval(50)
        self.update_timer.timeout.connect(self.update_plots_from_buffer)

        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)

        # ========== 左侧控制面板 ==========
        # 内容放在滚动区内：窗口/屏幕高度不足时改为滚动，
        # 而不是把 QGroupBox、输入框强行压扁导致字段相互遮挡
        left_inner = QWidget()
        left_inner.setObjectName("leftPanel")  # 对应 QSS 中的紧凑字号规则
        left_layout = QVBoxLayout(left_inner)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("📊 YC日志分析平台")
        title.setObjectName("appTitle")
        left_layout.addWidget(title)

        # 模式选择
        mode_group = QGroupBox("工作模式")
        mode_layout = QHBoxLayout()
        self.offline_radio = QRadioButton("离线模式")
        self.online_radio = QRadioButton("在线模式")
        self.offline_radio.setChecked(True)
        self.offline_radio.toggled.connect(self.on_mode_changed)
        self.online_radio.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.offline_radio)
        mode_layout.addWidget(self.online_radio)
        mode_group.setLayout(mode_layout)
        left_layout.addWidget(mode_group)

        self.stacked_widget = QStackedWidget()
        left_layout.addWidget(self.stacked_widget)

        # ----- 离线模式页面 -----
        offline_widget = QWidget()
        offline_layout = QVBoxLayout(offline_widget)
        offline_layout.setSpacing(8)

        path_group = QGroupBox("本地路径")
        path_layout = QVBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择文件或文件夹...")
        # 路径文本一经改动（手动编辑/重新选择）即放弃此前拖入的多文件列表
        self.path_edit.textChanged.connect(self._on_path_text_changed)
        path_layout.addWidget(self.path_edit)
        btn_layout = QHBoxLayout()
        self.file_btn = QPushButton("选择文件")
        self.file_btn.clicked.connect(self.select_file)
        self.folder_btn = QPushButton("选择文件夹")
        self.folder_btn.clicked.connect(self.select_folder)
        self.load_btn = QPushButton("加载")
        self.load_btn.setProperty("class", "primary")
        self.load_btn.setToolTip("解析并加载日志数据（也可直接将文件/文件夹拖入窗口）")
        self.load_btn.clicked.connect(self.start_load)
        btn_layout.addWidget(self.file_btn)
        btn_layout.addWidget(self.folder_btn)
        btn_layout.addWidget(self.load_btn)
        path_layout.addLayout(btn_layout)
        path_group.setLayout(path_layout)
        offline_layout.addWidget(path_group)

        opt_group = QGroupBox("选项")
        opt_layout = QVBoxLayout()
        cache_row = QHBoxLayout()
        self.cache_cb = QCheckBox("启用缓存")
        self.cache_cb.setChecked(True)
        self.cache_cb.stateChanged.connect(self.on_cache_toggle)
        self.rebuild_btn = QPushButton("🔄 重建缓存")
        self.rebuild_btn.clicked.connect(self.rebuild_cache)
        self.rebuild_btn.setEnabled(False)
        cache_row.addWidget(self.cache_cb)
        cache_row.addWidget(self.rebuild_btn)
        opt_layout.addLayout(cache_row)
        self.relative_time_cb = QCheckBox("使用相对时间")
        self.relative_time_cb.setChecked(True)
        self.relative_time_cb.setToolTip("忽略日志原始时间戳")
        opt_layout.addWidget(self.relative_time_cb)
        opt_group.setLayout(opt_layout)
        offline_layout.addWidget(opt_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setToolTip("中止当前加载任务")
        self.cancel_btn.clicked.connect(self.cancel_load)
        self.cancel_btn.setEnabled(False)
        offline_layout.addWidget(self.progress_bar)
        offline_layout.addWidget(self.cancel_btn)

        self.info_label = QLabel("未加载数据")
        self.info_label.setWordWrap(True)
        self.info_label.setProperty("class", "card")
        self.info_label.setMinimumHeight(54)  # 预留多行高度，窗口变小时文字不被裁剪
        offline_layout.addWidget(self.info_label)

        offline_layout.addStretch()
        self.stacked_widget.addWidget(offline_widget)

        # ----- 在线模式页面 -----
        online_widget = QWidget()
        online_layout = QVBoxLayout(online_widget)
        online_layout.setSpacing(8)

        dev_type_layout = QHBoxLayout()
        dev_type_layout.addWidget(QLabel("设备类型:"))
        self.device_type = QComboBox()
        if config:
            device_types = config.get_online_device_types()
            if device_types:
                self.device_type.addItems(device_types)
            else:
                # 降级硬编码
                self.device_type.addItems(["从手", "主手", "ADS"])
        else:
            self.device_type.addItems(["从手", "主手", "ADS"])
        self.device_type.currentTextChanged.connect(self.on_device_type_changed)
        dev_type_layout.addWidget(self.device_type)
        online_layout.addLayout(dev_type_layout)

        conn_group = QGroupBox("SSH连接")
        conn_layout = QVBoxLayout()
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("IP地址:"))
        self.ip_edit = QLineEdit("192.168.11.11")
        ip_layout.addWidget(self.ip_edit)
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("端口:"))
        self.port_edit = QLineEdit("22")
        port_layout.addWidget(self.port_edit)
        conn_layout.addLayout(ip_layout)
        conn_layout.addLayout(port_layout)
        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("用户名:"))
        self.user_edit = QLineEdit("codeit")
        user_layout.addWidget(self.user_edit)
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(QLabel("密码:"))
        self.passwd_edit = QLineEdit("1")
        self.passwd_edit.setEchoMode(QLineEdit.Password)
        pass_layout.addWidget(self.passwd_edit)
        conn_layout.addLayout(user_layout)
        conn_layout.addLayout(pass_layout)
        conn_group.setLayout(conn_layout)
        online_layout.addWidget(conn_group)

        monitor_layout = QHBoxLayout()
        self.connect_btn = QPushButton("连接并开始监控")
        self.connect_btn.setProperty("class", "primary")
        self.connect_btn.setToolTip("通过 SSH 连接远程设备并实时监控日志")
        self.connect_btn.clicked.connect(self.start_live)
        self.stop_live_btn = QPushButton("停止监控")
        self.stop_live_btn.setProperty("class", "danger")
        self.stop_live_btn.setToolTip("断开所有 SSH 连接并停止记录")
        self.stop_live_btn.setEnabled(False)
        self.stop_live_btn.clicked.connect(self.stop_live)
        monitor_layout.addWidget(self.connect_btn)
        monitor_layout.addWidget(self.stop_live_btn)
        online_layout.addLayout(monitor_layout)

        pause_layout = QHBoxLayout()
        self.pause_btn = QPushButton("⏸️ 暂停")
        self.pause_btn.setToolTip("暂停实时数据记录（快捷键 P）")
        self.pause_btn.clicked.connect(self.pause_live)
        self.pause_btn.setEnabled(False)
        self.resume_btn = QPushButton("▶️ 继续")
        self.resume_btn.setToolTip("继续实时数据记录（快捷键 P）")
        self.resume_btn.clicked.connect(self.resume_live)
        self.resume_btn.setEnabled(False)
        # P 键切换暂停/继续
        QShortcut(Qt.Key_P, self, self._toggle_pause)
        pause_layout.addWidget(self.pause_btn)
        pause_layout.addWidget(self.resume_btn)
        online_layout.addLayout(pause_layout)

        buffer_group = QGroupBox("数据缓冲区")
        buffer_layout = QHBoxLayout()
        buffer_layout.addWidget(QLabel("保留时间:"))
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(1, 120)
        self.buffer_spin.setSingleStep(1)
        self.buffer_spin.setValue(self.buffer_seconds)
        self.buffer_spin.setSuffix(" s")
        self.buffer_spin.setToolTip("缓冲区保留时长：决定绘图区可回看的数据范围")
        self.buffer_spin.valueChanged.connect(self.on_buffer_size_changed)
        buffer_layout.addWidget(self.buffer_spin)
        buffer_group.setLayout(buffer_layout)
        online_layout.addWidget(buffer_group)

        self.online_info_label = QLabel("未连接")
        self.online_info_label.setWordWrap(True)
        self.online_info_label.setProperty("class", "card")
        self.online_info_label.setMinimumHeight(40)  # 预留多行高度，窗口变小时文字不被裁剪
        online_layout.addWidget(self.online_info_label)

        online_layout.addStretch()
        self.stacked_widget.addWidget(online_widget)

        # 数据列树（支持拖拽）
        section_label = QLabel("📋 数据列")
        section_label.setObjectName("sectionLabel")
        left_layout.addWidget(section_label)
        self.tree = DragTreeWidget()
        self.tree.setHeaderLabel("数据列")
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setIndentation(20)
        self.tree.setMinimumHeight(240)  # 数据列区域留出足够高度，窗口不足时由左侧滚动区滚动
        self.tree.setAlternatingRowColors(True)   # 斑马纹提升长列表可读性
        self.tree.setAnimated(True)               # 展开/折叠平滑动画
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)  # 平滑滚动
        self.tree.setAccessibleName("数据列树，可将数据列拖入绘图区")
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        # stretch=1：窗口变高时把多余空间让给数据列树（不再被下面的弹簧吃掉）
        left_layout.addWidget(self.tree, 1)

        # 清除当前页所有曲线按钮
        clear_btn = QPushButton("🗑️ 清除当前页所有曲线")
        clear_btn.setProperty("class", "danger")
        clear_btn.setToolTip("移除当前标签页内的全部曲线")
        clear_btn.clicked.connect(self.clear_current_tab_curves)
        left_layout.addWidget(clear_btn)

        self.save_btn = QPushButton("💾 保存当前页图像")
        self.save_btn.setToolTip("将当前标签页导出为 PNG/JPEG/BMP 图像")
        self.save_btn.clicked.connect(self.save_current_figure)
        left_layout.addWidget(self.save_btn)

        # logo（与 launcher 风格一致）
        logo_label = QLabel("Made with TC❤️")
        logo_label.setObjectName("logoLabel")
        logo_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(logo_label)

        # 左侧面板整体放入滚动区：内容超出可用高度时出现滚动条，控件永不被压扁
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)   # 空间足够时拉伸填满，不足时滚动
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 宽度由面板自适应，不出现横向滚动
        left_scroll.setWidget(left_inner)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        left_scroll.setMinimumWidth(340)
        left_scroll.setMaximumWidth(560)
        main_layout.addWidget(left_scroll)

        # ========== 右侧绘图区域 ==========
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        self.tab_widget = QTabWidget()
        # 关闭按钮由 _install_tab_close_button 自绘（Qt 默认那个在自定义 QSS 下很丑）
        self.tab_widget.setTabsClosable(False)

        # 右上角工具栏按钮组
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(2)

        # 水平分栏按钮（左右并排 → 竖线分隔图标）
        self.h_split_btn = QPushButton(split_icon("vertical"), "")
        self.h_split_btn.setIconSize(QSize(16, 16))
        self.h_split_btn.setToolTip("水平分栏（左右并排）")
        self.h_split_btn.setFixedSize(30, 30)
        self.h_split_btn.setProperty("class", "icon")
        self.h_split_btn.setAccessibleName("水平分栏")
        self.h_split_btn.clicked.connect(self.split_current_tab_horizontal)
        corner_layout.addWidget(self.h_split_btn)

        # 垂直分栏按钮（上下堆叠 → 横线分隔图标）
        self.v_split_btn = QPushButton(split_icon("horizontal"), "")
        self.v_split_btn.setIconSize(QSize(16, 16))
        self.v_split_btn.setToolTip("垂直分栏（上下堆叠）")
        self.v_split_btn.setFixedSize(30, 30)
        self.v_split_btn.setProperty("class", "icon")
        self.v_split_btn.setAccessibleName("垂直分栏")
        self.v_split_btn.clicked.connect(self.split_current_tab_vertical)
        corner_layout.addWidget(self.v_split_btn)

        # 新建标签页按钮
        self.new_tab_btn = QPushButton(plus_icon(), "")
        self.new_tab_btn.setIconSize(QSize(16, 16))
        self.new_tab_btn.setFixedSize(30, 30)
        self.new_tab_btn.setProperty("class", "icon")
        self.new_tab_btn.setToolTip("新建标签页")
        self.new_tab_btn.setAccessibleName("新建标签页")
        self.new_tab_btn.clicked.connect(self.new_plot_tab)
        corner_layout.addWidget(self.new_tab_btn)

        # 垂直游标切换按钮
        self.cursor_btn = QPushButton(cursor_icon(0), "")
        self.cursor_btn.setIconSize(QSize(16, 16))
        self.cursor_btn.setToolTip("切换游标A (Tab键切换活动游标, 左右箭头移动)")
        self.cursor_btn.setFixedSize(30, 30)
        self.cursor_btn.setProperty("class", "icon")
        self.cursor_btn.setAccessibleName("切换游标A")
        self.cursor_btn.setCheckable(True)
        self.cursor_btn.clicked.connect(lambda: self.toggle_current_tab_cursor(0))
        corner_layout.addWidget(self.cursor_btn)

        self.cursor2_btn = QPushButton(cursor_icon(1), "")
        self.cursor2_btn.setIconSize(QSize(16, 16))
        self.cursor2_btn.setToolTip("切换游标B (Tab键切换活动游标, 左右箭头移动)")
        self.cursor2_btn.setFixedSize(30, 30)
        self.cursor2_btn.setProperty("class", "icon")
        self.cursor2_btn.setAccessibleName("切换游标B")
        self.cursor2_btn.setCheckable(True)
        self.cursor2_btn.clicked.connect(lambda: self.toggle_current_tab_cursor(1))
        corner_layout.addWidget(self.cursor2_btn)

        # 时间跳转按钮
        self.time_jump_btn = QPushButton(clock_icon(), "")
        self.time_jump_btn.setIconSize(QSize(16, 16))
        self.time_jump_btn.setToolTip("跳转到指定时间 (J)")
        self.time_jump_btn.setFixedSize(30, 30)
        self.time_jump_btn.setProperty("class", "icon")
        self.time_jump_btn.setAccessibleName("跳转到指定时间")
        self.time_jump_btn.clicked.connect(self._jump_cursor_to_time)
        corner_layout.addWidget(self.time_jump_btn)

        # Ctrl+T 快捷键触发时间跳转
        QShortcut(Qt.Key_J, self, self._jump_cursor_to_time)

        self.tab_widget.setCornerWidget(corner_widget, Qt.TopRightCorner)

        self.default_tab = PlotTab(self, "绘图1")
        self.tab_widget.addTab(self.default_tab, "绘图1")
        self._install_tab_close_button(0)
        self.tab_widget.currentChanged.connect(self._on_plot_tab_changed)
        right_layout.addWidget(self.tab_widget, stretch=1)

        main_layout.addWidget(right_container, stretch=1)

    # ========== 屏幕切换 / 窗口尺寸 ==========
    def event(self, e):
        # 窗口切换屏幕（如拖至副屏）后刷新界面布局，修复网格错位、元素错乱
        if _SCREEN_CHANGE_TYPE is not None and e.type() == _SCREEN_CHANGE_TYPE:
            QTimer.singleShot(150, self._refresh_ui_after_screen_change)
        return super().event(e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'tab_widget'):
            return
        if not hasattr(self, '_resize_timer'):
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._after_resize)
        self._resize_timer.start(300)  # 去抖：拖动结束后才刷新

    def _after_resize(self):
        """窗口尺寸调整完成后：重新对齐各子图左轴（网格对齐）"""
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, '_align_left_axes'):
                tab._align_left_axes()

    def _start_post_load_heartbeat(self):
        """加载完成后启动短时心跳日志。

        用于区分两种崩溃场景：若崩溃发生在加载完成后，心跳会戛然而止；
        若进程能持续输出心跳，说明退出发生在用户后续操作阶段。
        """
        if not hasattr(self, '_hb_timer'):
            self._hb_timer = QTimer(self)
            self._hb_timer.timeout.connect(self._on_heartbeat)
        self._hb_left = 10  # 10 次 × 2s，覆盖加载完成后的关键 20 秒
        self._hb_timer.start(2000)

    def _on_heartbeat(self):
        log("心跳：程序运行中")
        self._hb_left -= 1
        if self._hb_left <= 0:
            self._hb_timer.stop()

    def _refresh_ui_after_screen_change(self):
        """窗口移动到其他屏幕后：重算布局、对齐坐标轴并强制重绘绘图区"""
        if not hasattr(self, 'tab_widget'):
            return
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'sub_widgets'):
                tab._align_left_axes()
                for sub in tab.sub_widgets:
                    pw = sub.plot_widget
                    pw.updateGeometry()
                    pw.getViewBox().update()
                    pw.getPlotItem().update()
                    pw.repaint()
        # 重新自适应树表头宽度（DPI 变化后字体尺寸会变）
        self.tree.header().resizeSections(QHeaderView.ResizeToContents)
        self.statusBar().showMessage("已切换显示设备，界面布局已刷新")

    # ========== 标签页管理 ==========
    def _install_tab_close_button(self, index):
        """给第 index 个标签页装一个自绘 ✕ 按钮"""
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QSize(9, 9))
        btn.setFixedSize(16, 16)
        btn.setToolTip("关闭此页")
        btn.setAccessibleName("关闭此页")
        btn.setStyleSheet(
            "QToolButton{background:transparent;border-radius:8px;}"
            "QToolButton:hover{background:rgba(255,255,255,0.35);}"
            "QToolButton:pressed{background:rgba(255,255,255,0.55);}")
        # 用 widget 反查下标，删掉前面的页后索引会平移
        tab = self.tab_widget.widget(index)
        btn.clicked.connect(
            lambda _=False, t=tab: self.close_tab(self.tab_widget.indexOf(t)))
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, btn)
        self._refresh_tab_close_icons()

    def _refresh_tab_close_icons(self):
        """选中的标签页是蓝底，✕ 得换成白色才看得清"""
        for i in range(self.tab_widget.count()):
            btn = self.tab_widget.tabBar().tabButton(i, QTabBar.RightSide)
            if btn is not None:
                white = (i == self.tab_widget.currentIndex())
                btn.setIcon(close_x_icon(9, "#FFFFFF" if white else "#475569"))

    def new_plot_tab(self):
        count = self.tab_widget.count() + 1
        new_tab = PlotTab(self, f"绘图{count}")
        self.tab_widget.addTab(new_tab, f"绘图{count}")
        self._install_tab_close_button(self.tab_widget.count() - 1)
        self.tab_widget.setCurrentWidget(new_tab)

    def close_tab(self, index):
        if index < 0 or self.tab_widget.count() <= 1:
            QMessageBox.information(self, "提示", "至少需要保留一个标签页")
            return
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        widget.deleteLater()
        # 在线模式：标签页关闭后其曲线不再参与记录目标计算
        self._refresh_recording_targets()

    def clear_current_tab_curves(self):
        current_tab = self.tab_widget.currentWidget()
        if current_tab:
            current_tab.clear_all_curves()

    def split_current_tab_horizontal(self):
        current = self.tab_widget.currentWidget()
        if current and hasattr(current, 'split_horizontal'):
            current.split_horizontal()

    def split_current_tab_vertical(self):
        current = self.tab_widget.currentWidget()
        if current and hasattr(current, 'split_vertical'):
            current.split_vertical()

    def toggle_current_tab_cursor(self, cursor_idx=0):
        """切换当前标签页的垂直游标"""
        tab = self.tab_widget.currentWidget()
        if tab and isinstance(tab, PlotTab):
            tab.toggle_cursor(cursor_idx=cursor_idx)
            self.cursor_btn.setChecked(tab.cursor_enabled[0])
            self.cursor2_btn.setChecked(tab.cursor_enabled[1])

    def _on_plot_tab_changed(self, index):
        """切换标签页时同步游标按钮状态"""
        self._refresh_tab_close_icons()
        tab = self.tab_widget.widget(index)
        if isinstance(tab, PlotTab):
            self.cursor_btn.setChecked(tab.cursor_enabled[0])
            self.cursor2_btn.setChecked(tab.cursor_enabled[1])

    def _jump_cursor_to_time(self):
        """弹出时间输入对话框，跳转到指定时间"""
        tab = self.tab_widget.currentWidget()
        if not isinstance(tab, PlotTab):
            return
        time_str, ok = QInputDialog.getText(
            self, "时间跳转",
            "输入目标时间",
            text=self._last_time_jump_text
        )
        if ok:
            if time_str:
                self._last_time_jump_text = time_str
                tab.jump_to_time(time_str)

    def save_current_figure(self):
        current_tab = self.tab_widget.currentWidget()
        if not current_tab or not current_tab.sub_widgets:
            QMessageBox.information(self, "提示", "当前标签页没有曲线可保存")
            return
        has_any_curve = any(sub.plot_items for sub in current_tab.sub_widgets)
        if not has_any_curve:
            QMessageBox.information(self, "提示", "当前标签页没有曲线可保存")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存图像", "",
                                            "PNG图片 (*.png);;JPEG图片 (*.jpg);;BMP图片 (*.bmp)")
        if path:
            pixmap = current_tab.grab()
            if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                pixmap.save(path)
                self.statusBar().showMessage(f"图像已保存至: {path}")
            else:
                pixmap.save(path + ".png")
                self.statusBar().showMessage(f"图像已保存至: {path}.png")

    # ========== 模式切换 ==========
    def on_mode_changed(self):
        if self.offline_radio.isChecked():
            self.stacked_widget.setCurrentIndex(0)
            self.stop_live()
        else:
            self.stacked_widget.setCurrentIndex(1)

    # ========== 在线模式辅助函数 ==========

    def on_device_type_changed(self):
        if self._is_any_thread_running():
            self.stop_live()
            QMessageBox.information(self, "提示", "设备类型已更改，已停止当前监控。请重新连接。")

    def on_buffer_size_changed(self, new_seconds):
        if new_seconds == self.buffer_seconds:
            return
        self.buffer_seconds = new_seconds
        new_points = new_seconds * 1000
        new_points = max(1000, min(120000, new_points))
        new_y_buffers = {}
        for col, ybuf in self.y_buffers.items():
            new_ybuf = deque(maxlen=new_points)
            new_ybuf.extend(ybuf)
            new_y_buffers[col] = new_ybuf
        self.y_buffers = new_y_buffers
        # 按臂分别调整 x_buffers（x_buffer 与 y_buffer 同一臂频率一致，maxlen 相同）
        new_x_buffers = {}
        for prefix, xbuf in self.x_buffers.items():
            new_xbuf = deque(maxlen=new_points)
            new_xbuf.extend(xbuf)
            new_x_buffers[prefix] = new_xbuf
        self.x_buffers = new_x_buffers
        self.buffer_size = new_points
        # 同步所有子图的视口宽度
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'sub_widgets'):
                for sub in tab.sub_widgets:
                    sub.view_width = float(new_seconds)
        self.statusBar().showMessage(f"保留时间已调整为 {new_seconds} s")

    def _get_remote_paths(self):
        """返回 [(arm_prefix, remote_path), ...] 列表，从配置读取"""
        dev_type = self.device_type.currentText()
        if config:
            paths = config.get_online_paths(dev_type)
            if paths:
                return paths
        # 降级（兼容无配置文件或未找到）
        if dev_type == "从手":
            return [
                ("arm1", "/data/log/rt/mmsArm1/mmsArm1"),
                ("arm2", "/data/log/rt/mmsArm2/mmsArm2"),
                ("arm3", "/data/log/rt/mmsArm3/mmsArm3"),
                ("arm4", "/data/log/rt/mmsArm4/mmsArm4"),
                ("boom", "/data/log/rt/mmsBoom/mmsBoom"),
            ]
        elif dev_type == "主手":
            return [
                ("left", "/data/log/rt/LeftDataModel/LeftDataModel"),
                ("right", "/data/log/rt/RightDataModel/RightDataModel"),
            ]
        elif dev_type == "ADS":
            return [("ADS", "/data/log/rt/LOUT/LOUT")]
        else:
            return []

    def _pre_build_tree_and_buffers(self, dev_type):
        """根据设备类型预构建树和预分配 y_buffers（ADS 除外）"""
        self._tree_prebuilt = True
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self.current_columns.clear()

        if dev_type == "从手":
            slave_cols = config.get_columns('slave')   # 142
            boom_cols = config.get_columns('boom')     # 36
            for arm in ('arm1', 'arm2', 'arm3', 'arm4'):
                for col in slave_cols:
                    self.y_buffers[f"{arm}:{col}"] = deque(maxlen=self.buffer_size)
                self.x_buffers[arm] = deque(maxlen=self.buffer_size)
            for col in boom_cols:
                self.y_buffers[f"boom:{col}"] = deque(maxlen=self.buffer_size)
            self.x_buffers["boom"] = deque(maxlen=self.buffer_size)

            for arm_name in ('arm1', 'arm2', 'arm3', 'arm4', 'boom'):
                cols = boom_cols if arm_name == 'boom' else slave_cols
                arm_item = QTreeWidgetItem(self.tree)
                arm_item.setText(0, arm_name)
                groups = {}
                for col in cols:
                    if '[' in col and ']' in col:
                        var = col.split('[')[0]
                    elif '_' in col and col.split('_')[-1].isdigit():
                        var = col.rsplit('_', 1)[0]
                    else:
                        var = col
                    groups.setdefault(var, []).append(col)
                for var in sorted(groups.keys()):
                    var_item = QTreeWidgetItem(arm_item)
                    var_item.setText(0, var)
                    for c in sorted(groups[var], key=lambda x: int(re.search(r'\[(\d+)]$|_(\d+)$', x).group(1) or 0) if re.search(r'\[(\d+)]$|_(\d+)$', x) else (1, x)):
                        child = QTreeWidgetItem(var_item)
                        child.setText(0, c)
                        child.setData(0, Qt.UserRole, f"{arm_name}:{c}")
                        child.setToolTip(0, c)

        elif dev_type == "主手":
            master_cols = config.get_columns('master')
            for prefix in ('left', 'right'):
                for col in master_cols:
                    self.y_buffers[f"{prefix}:{col}"] = deque(maxlen=self.buffer_size)
                self.x_buffers[prefix] = deque(maxlen=self.buffer_size)
            for prefix in ('left', 'right'):
                arm_item = QTreeWidgetItem(self.tree)
                arm_item.setText(0, prefix)
                groups = {}
                for col in master_cols:
                    if '_' in col and col.split('_')[-1].isdigit():
                        var = col.rsplit('_', 1)[0]
                    else:
                        var = col
                    groups.setdefault(var, []).append(col)
                for var in sorted(groups.keys()):
                    var_item = QTreeWidgetItem(arm_item)
                    var_item.setText(0, var)
                    for c in sorted(groups[var]):
                        child = QTreeWidgetItem(var_item)
                        child.setText(0, c)
                        child.setData(0, Qt.UserRole, f"{prefix}:{c}")
                        child.setToolTip(0, c)

        elif dev_type == "boom":
            cols = config.get_columns('boom')
            for col in cols:
                self.y_buffers[f"boom:{col}"] = deque(maxlen=self.buffer_size)
            arm_item = QTreeWidgetItem(self.tree)
            arm_item.setText(0, "boom")
            groups = {}
            for col in cols:
                var = col.split('[')[0] if '[' in col else col
                groups.setdefault(var, []).append(col)
            for var in sorted(groups.keys()):
                var_item = QTreeWidgetItem(arm_item)
                var_item.setText(0, var)
                for c in sorted(groups[var]):
                    child = QTreeWidgetItem(var_item)
                    child.setText(0, c)
                    child.setData(0, Qt.UserRole, f"boom:{c}")
                    child.setToolTip(0, c)

        self.tree.collapseAll()
        self.tree.header().resizeSections(QHeaderView.ResizeToContents)
        self.tree.setUpdatesEnabled(True)

    def _is_any_thread_running(self):
        return hasattr(self, 'live_threads') and any(t.isRunning() for t in self.live_threads)

    def clear_online_data(self):
        for buf in self.x_buffers.values():
            buf.clear()
        self.y_buffers.clear()
        self.current_columns.clear()
        self._tree_prebuilt = False
        self._arm_active_cols = {}
        self.tree.clear()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'clear_all_curves'):
                tab.clear_all_curves()

    def _toggle_pause(self):
        if hasattr(self, 'live_threads') and self._is_any_thread_running():
            if self.pause_btn.isEnabled():
                self.pause_live()
            else:
                self.resume_live()

    def pause_live(self):
        if hasattr(self, 'live_threads'):
            for t in self.live_threads:
                if t and t.isRunning():
                    t.set_paused(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.statusBar().showMessage("实时监控已暂停")

    def resume_live(self):
        if hasattr(self, 'live_threads'):
            for t in self.live_threads:
                if t and t.isRunning():
                    t.set_paused(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.statusBar().showMessage("实时监控已恢复")

    # ========== 在线监控 ==========
    def start_live(self):
        self.clear_online_data()
        self._arm_active_cols = {}
        ip = self.ip_edit.text().strip()
        port = int(self.port_edit.text().strip())
        user = self.user_edit.text().strip()
        pwd = self.passwd_edit.text().strip()
        paths = self._get_remote_paths()

        if not ip or not user or not paths:
            QMessageBox.warning(self, "错误", "请填写完整的主机、用户名")
            return

        # 预构建树和预分配 y_buffers（已知格式；ADS 等动态格式除外）
        dev_type = self.device_type.currentText()
        if dev_type != "ADS" and config is not None:
            self._pre_build_tree_and_buffers(dev_type)
            if not self.y_buffers:
                self._tree_prebuilt = False  # 未知设备类型：回退为动态发现模式
        else:
            self._tree_prebuilt = False

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'follow_latest'):
                for sub in tab.sub_widgets:
                    sub.follow_latest = False
                    sub.follow_btn.setChecked(False)

        # 保存连接参数：支持某臂线程停止后（如无数据超时）按臂重启
        self._live_conn = {'ip': ip, 'port': port, 'user': user, 'pwd': pwd,
                           'paths': {p: path for p, path in paths}}
        self.live_threads = []
        self._start_next_thread(0, paths, ip, port, user, pwd)

        self.connect_btn.setEnabled(False)
        self.stop_live_btn.setEnabled(True)
        self.update_timer.start()
        if self._tree_prebuilt:
            self.online_info_label.setText("监控中（空闲）：将左侧数据列拖入绘图窗口后，才开始记录对应臂的数据")
        else:
            self.online_info_label.setText("正在监控中...")
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)

    def stop_live(self):
        if hasattr(self, 'live_threads'):
            for t in self.live_threads:
                if t:
                    t.stop()
            self.live_threads = []
        self._live_conn = None  # 阻止错峰启动流程继续创建新线程
        self._arm_active_cols = {}
        self.update_timer.stop()
        self.connect_btn.setEnabled(True)
        self.stop_live_btn.setEnabled(False)
        self.online_info_label.setText("未连接")
        self.statusBar().showMessage("实时监控已停止")
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)

    def _start_next_thread(self, idx, paths, ip, port, user, pwd):
        """递归错峰启动 SSH 线程，间隔 300ms"""
        if idx >= len(paths):
            return
        if self._live_conn is None:
            return  # 已停止监控：不再创建新线程
        prefix, remote_path = paths[idx]
        thread = LiveThread(ip, port, user, pwd, remote_path, arm_prefix=prefix)
        # 动态格式（如 ADS）需持续读取以发现数据列；已知格式默认空闲，拖入曲线后按需记录
        thread.recording_enabled = (not self._tree_prebuilt)
        thread.new_batch.connect(lambda batch, p=prefix: self.on_new_batch(batch, p))
        thread.error.connect(self.on_live_error)
        thread.status.connect(self.statusBar().showMessage)
        thread.start()
        self.live_threads.append(thread)
        # 应用当前已绘制曲线对应的记录目标（处理启动期间用户已拖入曲线的情况）
        self._refresh_recording_targets()
        if idx + 1 < len(paths):
            QTimer.singleShot(300, lambda: self._start_next_thread(idx + 1, paths, ip, port, user, pwd))

    def _find_live_thread(self, arm_prefix):
        """查找指定臂的运行中线程"""
        for t in self.live_threads:
            if t and getattr(t, 'arm_prefix', '') == arm_prefix and t.isRunning():
                return t
        return None

    def _spawn_live_thread(self, arm_prefix):
        """为指定臂重新启动读取线程（该臂线程此前因无数据等原因自动停止）"""
        conn = getattr(self, '_live_conn', None)
        if not conn or arm_prefix not in conn['paths']:
            return None
        thread = LiveThread(conn['ip'], conn['port'], conn['user'], conn['pwd'],
                            conn['paths'][arm_prefix], arm_prefix=arm_prefix)
        thread.new_batch.connect(lambda batch, p=arm_prefix: self.on_new_batch(batch, p))
        thread.error.connect(self.on_live_error)
        thread.status.connect(self.statusBar().showMessage)
        thread.start()
        self.live_threads.append(thread)
        # 清理已停止的旧线程引用
        self.live_threads = [t for t in self.live_threads if t.isRunning()]
        return thread

    def _refresh_recording_targets(self):
        """根据当前各标签页已绘制的曲线，动态调整在线数据记录目标：
        - 仅记录有曲线绘制的臂（用户正在操作的臂）及其已绘制的列
        - 无曲线的臂进入空闲（停止读取），重新拖入曲线时自动恢复记录
        - 切换操作对象（增删曲线）时自动切换记录目标"""
        if not getattr(self, 'live_threads', None):
            return
        # 收集所有已绘制曲线（差分曲线映射回其基列）
        plotted_bases = set()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'sub_widgets'):
                for sub in tab.sub_widgets:
                    for key in sub.plot_items:
                        k = key
                        while k.endswith('[diff]'):
                            k = k[:-6]
                        if k:
                            plotted_bases.add(k)
        # 按臂分组（在线模式列名带 "臂:" 前缀）
        arm_cols = {}
        for key in plotted_bases:
            if ':' in key:
                p, c = key.split(':', 1)
                arm_cols.setdefault(p, set()).add(c)
        # 新激活的列：其历史缓冲区与当前 x 轴时间不再对应（曲线曾被移除过），
        # 必须清空后重新与 x 同步追加，否则 x/y 尾部对齐会错位显示旧数据
        for p, cols in arm_cols.items():
            newly = cols - self._arm_active_cols.get(p, set())
            for c in newly:
                b = self.y_buffers.get(f"{p}:{c}")
                if b is not None:
                    b.clear()
        self._arm_active_cols = arm_cols
        dynamic_mode = not self._tree_prebuilt

        if dynamic_mode:
            # 动态格式（如 ADS）：需持续读取以发现数据列，不做列过滤
            for t in list(self.live_threads):
                if t and t.isRunning():
                    t.active_cols_bare = None
                    if not t.recording_enabled:
                        t.recording_enabled = True
            # 已停止的动态线程在有活动曲线时重启
            if arm_cols:
                conn = getattr(self, '_live_conn', None)
                if conn:
                    for p in conn['paths']:
                        if self._find_live_thread(p) is None:
                            t = self._spawn_live_thread(p)
                            if t is not None:
                                t.active_cols_bare = None
                                t.recording_enabled = True
            return

        # 已知格式：按臂针对性记录
        for t in list(self.live_threads):
            if not t or not t.isRunning():
                continue
            p = getattr(t, 'arm_prefix', '')
            if p in arm_cols:
                t.active_cols_bare = arm_cols[p]
                if not t.recording_enabled:
                    t.recording_enabled = True
                    t._need_seek_end = True  # 从最新数据开始记录
                    self.statusBar().showMessage(f"[{p}] 开始记录数据")
            else:
                if t.recording_enabled:
                    self.statusBar().showMessage(f"[{p}] 无活动曲线，停止读取")
                t.recording_enabled = False
                t.active_cols_bare = set()
        # 已绘制曲线的臂若线程已停止（如无数据超时自动停止），重新启动
        for p in arm_cols:
            if self._find_live_thread(p) is None:
                t = self._spawn_live_thread(p)
                if t is not None:
                    t.active_cols_bare = arm_cols[p]
                    t.recording_enabled = True
                    self.statusBar().showMessage(f"[{p}] 重新连接并开始记录数据")

    def on_new_batch(self, batch, arm_prefix):
        """接收某臂的批量数据，按需记录（仅记录当前操作的臂/列）"""
        if not batch:
            return
        if self._tree_prebuilt:
            # 已知格式：x 与已绘制列的 y 同步追加（缺失列以 NaN 占位保持对齐）
            xbuf = self.x_buffers.get(arm_prefix)
            active = self._arm_active_cols.get(arm_prefix)
            if xbuf is None or not active:
                return  # 该臂当前没有活动曲线：不记录
            yb = self.y_buffers
            pk = f"{arm_prefix}:"
            col_bufs = []
            for c in active:
                b = yb.get(pk + c)
                if b is not None:
                    col_bufs.append((c, b))
            if not col_bufs:
                return
            for epoch, data_dict in batch:
                xbuf.append(epoch)
                for c, b in col_bufs:
                    v = data_dict.get(c)
                    b.append(v if v is not None else float('nan'))
            # 按保留时间淘汰过期点（maxlen 仅作内存安全上限）
            self._evict_old_data(arm_prefix, [c for c, _ in col_bufs])
        else:
            # 动态格式（如 ADS）：动态建树 + 惰性 buffer 创建
            new_cols = []
            for epoch, data_dict in batch:
                xbuf = self.x_buffers.setdefault(arm_prefix, deque(maxlen=self.buffer_size))
                xbuf.append(epoch)
                for col, val in data_dict.items():
                    full = f"{arm_prefix}:{col}"
                    buf = self.y_buffers.get(full)
                    if buf is None:
                        buf = deque(maxlen=self.buffer_size)
                        self.y_buffers[full] = buf
                        new_cols.append(col)
                    buf.append(val)
            self._evict_old_data(arm_prefix)
            if new_cols:
                self._ensure_tree_items(arm_prefix, new_cols)

    def _evict_old_data(self, arm_prefix, active_cols=None):
        """按"保留时间"淘汰过期数据，使缓冲区的时间跨度严格等于设置值。

        淘汰依据是时间戳而非点数：x 轴按时间裁剪，各列 y 按其自身长度补齐，
        因此后加入的列（起始时间更晚）不会被误删。
        active_cols 为 None 时处理该臂的全部列（动态格式）。
        """
        xbuf = self.x_buffers.get(arm_prefix)
        if not xbuf:
            return
        cutoff = xbuf[-1] - float(self.buffer_seconds)
        dropped = False
        while xbuf and xbuf[0] < cutoff:
            xbuf.popleft()
            dropped = True
        if not dropped:
            return
        # 裁剪后 x 的长度即"窗口内应有的点数"；各列 y 与其尾部对齐，
        # 因此超出该长度的部分即为过期点
        keep = len(xbuf)
        pk = arm_prefix + ':'
        keys = ([pk + c for c in active_cols] if active_cols is not None
                else [k for k in self.y_buffers if k.startswith(pk)])
        for k in keys:
            b = self.y_buffers.get(k)
            if b is None:
                continue
            for _ in range(max(0, len(b) - keep)):
                b.popleft()

    def _ensure_tree_items(self, arm_prefix, bare_cols):
        """动态模式：为首次出现的列创建树节点"""
        for var_full in bare_cols:
            col = f"{arm_prefix}:{var_full}"
            if col in self.current_columns:
                continue
            self.current_columns.append(col)
            if '[' in var_full and ']' in var_full:
                var = var_full.split('[')[0]
            elif '_' in var_full and var_full.split('_')[-1].isdigit():
                var = var_full.rsplit('_', 1)[0]
            else:
                var = var_full
            arm_item = None
            for i in range(self.tree.topLevelItemCount()):
                if self.tree.topLevelItem(i).text(0) == arm_prefix:
                    arm_item = self.tree.topLevelItem(i)
                    break
            if not arm_item:
                arm_item = QTreeWidgetItem(self.tree)
                arm_item.setText(0, arm_prefix)
            var_item = None
            for i in range(arm_item.childCount()):
                if arm_item.child(i).text(0) == var:
                    var_item = arm_item.child(i)
                    break
            if not var_item:
                var_item = QTreeWidgetItem(arm_item)
                var_item.setText(0, var)
            child = QTreeWidgetItem(var_item)
            child.setText(0, var_full)
            child.setData(0, Qt.UserRole, col)  # 存储完整 key，拖拽时匹配 y_buffers
            child.setToolTip(0, var_full)

    def update_plots_from_buffer(self):
        if not self.x_buffers:
            return
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'update_curves'):
                tab.update_curves()

    def on_live_error(self, arm_prefix, msg):
        """单臂错误：仅停止该臂的读取，不影响其他臂的监控"""
        stopped = [t for t in self.live_threads
                   if t and getattr(t, 'arm_prefix', '') == arm_prefix]
        for t in stopped:
            t.stop()
        if stopped:
            self.live_threads = [t for t in self.live_threads if t not in stopped]
        self.statusBar().showMessage(f"[{arm_prefix}] 读取失败: {msg}")
        if not self._is_any_thread_running():
            self.stop_live()
            self.online_info_label.setText("监控已停止（所有臂均无数据或连接失败）")

    # ========== 拖放加载 ==========
    def dragEnterEvent(self, event):
        """接受文件/文件夹拖入"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """处理拖入的文件/文件夹（支持多文件）"""
        urls = event.mimeData().urls()
        if not urls:
            return
        # 收集所有有效路径
        paths = []
        for u in urls:
            p = u.toLocalFile()
            if p and os.path.exists(p):
                paths.append(p)

        if len(paths) == 1:
            path = paths[0]
            self.path_edit.setText(path)   # textChanged 会清空 _dropped_files
            self.force_rebuild = False
            if os.path.isdir(path):
                if self.use_cache:
                    self.rebuild_btn.setEnabled(True)
            else:
                self.rebuild_btn.setEnabled(False)
            self.start_load()
        elif len(paths) > 1:
            # 多文件：只保留普通文件，按第一行时间戳排序后加载
            log_files = [p for p in paths if os.path.isfile(p) and not is_compressed_file(p)]
            if not log_files:
                QMessageBox.information(self, "提示", "拖入的文件中没有可解析的日志文件")
                return
            log_files.sort(key=lambda f: get_file_first_timestamp(f) or datetime.datetime.min)
            # 多文件没有单一路径可用于回填 path_edit，此处仅作展示，
            # 真正的待加载列表存入 _dropped_files，点击“加载”时复用
            self.path_edit.setText(f"拖放 {len(log_files)} 个文件")
            self._dropped_files = log_files
            self.force_rebuild = False
            self.rebuild_btn.setEnabled(False)
            self.start_load()

    # ========== 离线模式方法 ==========
    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择日志文件", "", "所有文件 (*.*)")
        if path:
            self.path_edit.setText(path)
            self.rebuild_btn.setEnabled(False)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if folder:
            self.path_edit.setText(folder)
            if self.use_cache:
                self.rebuild_btn.setEnabled(True)

    def on_cache_toggle(self, state):
        self.use_cache = (state == Qt.Checked)
        if self.use_cache and self.path_edit.text() and os.path.isdir(self.path_edit.text()):
            self.rebuild_btn.setEnabled(True)
        else:
            self.rebuild_btn.setEnabled(False)

    def rebuild_cache(self):
        folder = self.path_edit.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "错误", "请先选择一个文件夹")
            return
        cache_path = os.path.join(folder, CACHE_FILENAME)
        if os.path.exists(cache_path):
            os.remove(cache_path)
        # 同时清理旧版 parquet 缓存，避免与新缓存混用
        legacy = os.path.join(folder, LEGACY_CACHE_FILENAME)
        if os.path.exists(legacy):
            try:
                os.remove(legacy)
            except Exception:
                pass
        self.force_rebuild = True
        self.start_load()

    def _on_path_text_changed(self, _text):
        """路径文本变化（手动编辑或重新选择）后，不再沿用拖入的多文件列表"""
        self._dropped_files = None

    def start_load(self):
        # 多文件拖入时 path_edit 里只有展示文本，真实列表存在 _dropped_files
        files = self._dropped_files
        if files:
            path = files[0]
        else:
            path = self.path_edit.text().strip()
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "错误", "路径不存在")
                return

        self.load_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.rebuild_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.folder_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.info_label.setText("加载中...")
        self.tree.clear()

        self.load_thread = LoadThread(path, self.use_cache, self.force_rebuild,
                                      use_relative_time=self.relative_time_cb.isChecked(),
                                      files=files)
        self.load_thread.progress.connect(self.update_progress)
        self.load_thread.finished.connect(self.load_finished)
        self.load_thread.start()
        self.force_rebuild = False

    def cancel_load(self):
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.stop_load()
            self.cancel_btn.setEnabled(False)

    def update_progress(self, value):
        self.progress_bar.setValue(int(value * 100))
        
    def clear_all_tabs_curves(self):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'clear_all_curves'):
                tab.clear_all_curves()

    def load_finished(self, df, cancelled, error):
        log(f"load_finished 开始 | 行数={len(df)} | 取消={cancelled} | 错误={error!r}")
        try:
            self.load_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.file_btn.setEnabled(True)
            self.folder_btn.setEnabled(True)
            if self.use_cache and self.path_edit.text() and os.path.isdir(self.path_edit.text()):
                self.rebuild_btn.setEnabled(True)
            self.progress_bar.setValue(100)

            if cancelled:
                self.info_label.setText("加载已取消")
                return
            if error:
                QMessageBox.critical(self, "错误", f"加载失败:\n{error}")
                self.info_label.setText("加载失败")
                return
            if df.empty:
                # 区分"日志格式不识别"与"确实没有数据"，给出可操作的提示
                if config is None:
                    QMessageBox.warning(
                        self, "警告",
                        "未找到数据格式配置文件 configs/data_formats.json，无法解析日志。\n\n"
                        "请将 configs 文件夹与程序放在同一目录后重试。")
                else:
                    QMessageBox.warning(self, "警告", "未找到有效日志数据")
                self.info_label.setText("未加载数据")
                return

            # 限制最大列数，防止 UI 卡死
            MAX_COLS = 150
            if len(df.columns) > MAX_COLS:
                reply = QMessageBox.question(self, "警告", 
                                            f"数据列过多 ({len(df.columns)} 列)，可能影响性能。是否只显示前 {MAX_COLS} 列？",
                                            QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    keep_cols = ['timestamp', 'line_no'] + [c for c in df.columns if c not in ('timestamp', 'line_no')][:MAX_COLS]
                    df = df[keep_cols]
                    QMessageBox.information(self, "提示", f"已截断，当前共 {len(df.columns)} 列")
                else:
                    # 用户选择不截断，但仍建议继续，可能会崩溃
                    pass

            # 清除旧数据
            self.tree.blockSignals(True)
            self.tree.clear()
            self.current_columns.clear()
            self.clear_current_tab_curves()   # 清除当前标签页曲线

            self.df = df
            # 预计算时间戳 epoch
            use_relative = self.relative_time_cb.isChecked() and 'line_no' in df.columns
            # DISPLAY 格式直接用 count 值作为时间轴
            if '__display_time__' in df.columns:
                self.timestamp_epoch = df['__display_time__'].values.astype(float)
                df = df.drop(columns=['__display_time__'])
                self.df = df  # 同步移除内部辅助列，避免干扰曲线/差分数据源查找
            elif 'timestamp' in df.columns and df['timestamp'].notna().any():
                if use_relative:
                    # 相对时间模式只用得到第一个时间戳作为基准，
                    # 因此无需逐行转换。原先逐行调用 to_pydatetime().timestamp()
                    # 在数万～数十万行时既极慢，又是原生崩溃的高发点。
                    base0 = _first_timestamp_epoch(df['timestamp'])
                    self.timestamp_epoch = np.array([base0]) if base0 is not None else None
                else:
                    try:
                        self.timestamp_epoch = _timestamps_to_epoch(df['timestamp'])
                    except Exception as e:
                        log(f"时间戳转换失败: {e}")
                        self.timestamp_epoch = None
            else:
                self.timestamp_epoch = None

            # 如果勾选了相对时间，以第一个时间戳为基准，按行号生成时间轴（忽略原始时间戳间隔）
            if use_relative:
                if self.timestamp_epoch is not None and len(self.timestamp_epoch) > 0 and not np.isnan(self.timestamp_epoch[0]):
                    base = self.timestamp_epoch[0]
                else:
                    base = 0.0
                self.timestamp_epoch = base + (df['line_no'].values - 1) * 0.001

            self.current_columns = [c for c in df.columns if c not in ('timestamp', 'line_no')]
            group_dict = {}
            for col in self.current_columns:
                # 解析变量名
                if '[' in col and ']' in col:
                    var = col.split('[')[0]
                elif '_' in col and col.split('_')[-1].isdigit():
                    var = '_'.join(col.split('_')[:-1])
                elif col.split('_')[0].isdigit() and '_' in col:
                    var = col.split('_')[0]
                else:
                    var = col
                group_dict.setdefault(var, []).append(col)

            # 禁用更新，提高性能
            self.tree.setUpdatesEnabled(False)
            for var in sorted(group_dict.keys()):
                parent = QTreeWidgetItem(self.tree)
                parent.setText(0, var)
                # 按数值索引排序：cur_pos[2] 排在 cur_pos[10] 之前
                def _col_sort_key(c):
                    m = re.search(r'\[(\d+)\]$|_(\d+)$', c)
                    if m:
                        return (0, int(m.group(1) or m.group(2)))
                    return (1, c)
                for col in sorted(group_dict[var], key=_col_sort_key):
                    child = QTreeWidgetItem(parent)
                    child.setText(0, col)
                    child.setToolTip(0, col)
            self.tree.collapseAll()
            self.tree.header().resizeSections(QHeaderView.ResizeToContents)
            self.tree.setUpdatesEnabled(True)
            self.tree.blockSignals(False)

            time_range = ""
            if self.relative_time_cb.isChecked() and 'line_no' in df.columns:
                total_s = (df['line_no'].max() - 1) * 0.001
                base_ts = df['timestamp'].iloc[0] if 'timestamp' in df.columns and not df['timestamp'].empty else None
                if base_ts is not None and pd.notna(base_ts):
                    time_range = f"\n相对时间（基准 {base_ts}，跨度 {total_s:.3f} s）"
                else:
                    time_range = f"\n相对时间: 0 ~ {total_s:.3f} s"
            elif 'timestamp' in df.columns and df['timestamp'].notna().any():
                tmin = df['timestamp'].min()
                tmax = df['timestamp'].max()
                time_range = f"\n时间范围: {tmin} ~ {tmax}"

            self.info_label.setText(f"✅ 已加载 {len(df)} 行，共 {len(self.current_columns)} 个数据列{time_range}")
            self.statusBar().showMessage(f"加载成功：{len(df)} 行数据")
            log(f"load_finished 完成 | 列数={len(self.current_columns)} | 时间轴={self.timestamp_epoch is not None}")
            self._start_post_load_heartbeat()
        except Exception as e:
            log('load_finished 异常:\n' + traceback.format_exc())
            QMessageBox.critical(self, "加载错误", f"发生异常：{str(e)}\n请检查日志文件格式或尝试减少文件数量。")
            self.info_label.setText("加载失败")
        log("load_finished 返回（已回到事件循环）")

def main():
    # 最先安装崩溃捕获：窗口程序无控制台，静默退出时靠日志定位原因
    setup_crash_logging()
    # 高 DPI / 多显示器支持：必须在 QApplication 创建之前设置，
    # 否则主副屏缩放比例不一致时会出现网格错位、控件错乱、坐标偏移
    if sys.platform == 'win32':
        try:
            import ctypes
            # PER_MONITOR_DPI_AWARE：窗口跨屏移动时按各屏实际 DPI 渲染
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    # Fusion 风格作为基底：QSS 渲染跨平台一致，配合全局样式表实现现代外观
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(MODERN_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()