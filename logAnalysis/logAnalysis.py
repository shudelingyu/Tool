#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import datetime
import paramiko
from collections import deque
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QLineEdit,
                             QFileDialog, QMessageBox, QProgressBar, QSpinBox, QSplitter,
                            QAbstractItemView, QGroupBox, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QComboBox, QSizePolicy,
                             QRadioButton, QStackedWidget, QTabWidget, QHeaderView)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QMimeData, QEvent
from PyQt5.QtGui import QDrag
import pyqtgraph as pg
import pandas as pd
import numpy as np

# 设置 PyQtGraph 全局背景白色、前景黑色
pg.setConfigOptions(background='w', foreground='k')
pg.setConfigOptions(antialias=True)

# ==================== 日志解析模块（保持不变） ====================
TIMESTAMP_PAT = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*')
MASTER_NUM_PAT = re.compile(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?')

_FULL_SLAVE_COLS = None
_SIMPLE_SLAVE_COLS = None
_SIMPLE_TO_FULL_MAP = None
_MASTER_COLS = None

def parse_timestamp(line: str):
    m = TIMESTAMP_PAT.match(line)
    if m:
        return m.group(1), line[m.end():]
    return None, line

def get_full_slave_columns():
    global _FULL_SLAVE_COLS
    if _FULL_SLAVE_COLS is None:
        vars_long = ['tar_pos', 'cur_pos', 'tar_toq', 'cur_toq', 'status_word',
                     'control_word', 'error_code', 'encoder1', 'encoder2', 'mode']
        cols = []
        for v in vars_long:
            cols.extend([f'{v}[{i}]' for i in range(13)])
        cols.extend([f'pa[{i}]' for i in range(6)])
        cols.extend([f'ff_PDO[{i}]' for i in range(5)])
        cols.append('motion_cmd')
        _FULL_SLAVE_COLS = cols
    return _FULL_SLAVE_COLS

def get_simple_slave_columns():
    global _SIMPLE_SLAVE_COLS
    if _SIMPLE_SLAVE_COLS is None:
        vars_short = ['tar_pos', 'cur_pos', 'tar_toq', 'cur_toq', 'status_word',
                      'control_word', 'error_code', 'encoder1', 'encoder2', 'mode']
        cols = []
        for v in vars_short:
            cols.extend([f'{v}[{i}]' for i in range(5, 13)])
        cols.extend([f'pa[{i}]' for i in range(6)])
        cols.extend([f'ff_PDO[{i}]' for i in range(5)])
        cols.append('motion_cmd')
        _SIMPLE_SLAVE_COLS = cols
    return _SIMPLE_SLAVE_COLS

def get_boom_columns():
    variables = ['tar_pos', 'cur_pos', 'tar_toq', 'cur_toq',
                 'status_word', 'control_word', 'error_code',
                 'encoder1', 'encoder2']
    cols = []
    for var in variables:
        for i in range(4):
            cols.append(f'{var}[{i}]')
    return cols

def get_simple_to_full_indices():
    global _SIMPLE_TO_FULL_MAP
    if _SIMPLE_TO_FULL_MAP is None:
        full_cols = get_full_slave_columns()
        simple_cols = get_simple_slave_columns()
        _SIMPLE_TO_FULL_MAP = [full_cols.index(col) for col in simple_cols]
    return _SIMPLE_TO_FULL_MAP

def get_master_columns():
    global _MASTER_COLS
    if _MASTER_COLS is None:
        fields = [
            ('cur_q', 8), ('cur_qabs', 8), ('tar_q', 8),
            ('pdo6064', 8), ('pdo20a0', 8), ('cur_toq', 8), ('tar_toq', 8),
            ('gravityTau', 7), ('feedbackTau', 7), ('cur_endpos', 12),
            ('clipratio', 1), ('hall', 1), ('io_finger_clutch', 1),
            ('control_word', 8), ('status_word', 8), ('error_code', 8),
            ('mode_of_operation', 8), ('motion_cmd', 1), ('view_angle', 1)
        ]
        cols = []
        for name, cnt in fields:
            if cnt == 1:
                cols.append(name)
            else:
                cols.extend([f'{name}_{i}' for i in range(cnt)])
        _MASTER_COLS = cols
    return _MASTER_COLS

def parse_slave_line_fast(data_part: str):
    if not data_part.startswith(','):
        return None, None
    parts = data_part[1:].split(',')
    n = len(parts)

    if n == 142:
        cols = get_full_slave_columns()
        values = []
        for p in parts:
            p = p.strip()
            if not p:
                values.append(np.nan)
                continue
            try:
                if '.' not in p and 'e' not in p.lower():
                    values.append(int(p))
                else:
                    values.append(float(p))
            except ValueError:
                values.append(np.nan)
        return cols, values

    elif n == 92:
        simple_vals = []
        for p in parts:
            p = p.strip()
            if not p:
                simple_vals.append(np.nan)
                continue
            try:
                if '.' not in p and 'e' not in p.lower():
                    simple_vals.append(int(p))
                else:
                    simple_vals.append(float(p))
            except ValueError:
                simple_vals.append(np.nan)

        full_vals = [0.0] * 142
        indices = get_simple_to_full_indices()
        for idx_simple, val in enumerate(simple_vals):
            full_vals[indices[idx_simple]] = val
        return get_full_slave_columns(), full_vals

    else:
        return None, None

def parse_master_line_fast(data_part: str):
    parts = data_part.strip().split()
    if not parts:
        return None, None

    fields = [
        ('cur_q', 8), ('cur_qabs', 8), ('tar_q', 8),
        ('pdo6064', 8), ('pdo20a0', 8), ('cur_toq', 8), ('tar_toq', 8),
        ('gravityTau', 7), ('feedbackTau', 7), ('cur_endpos', 12),
        ('clipratio', 1), ('hall', 1), ('io_finger_clutch', 1),
        ('control_word', 8), ('status_word', 8), ('error_code', 8),
        ('mode_of_operation', 8), ('motion_cmd', 1), ('view_angle', 1)
    ]

    values = []
    i = 0

    def _parse_number(tok):
        tok = tok.strip().rstrip(',')
        if tok == '':
            return np.nan
        try:
            if '.' in tok or 'e' in tok.lower():
                return float(tok)
            else:
                return int(tok)
        except Exception:
            try:
                return float(tok)
            except Exception:
                return np.nan

    for name, cnt in fields:
        if i < len(parts) and parts[i] == name:
            i += 1
        for _ in range(cnt):
            if i >= len(parts):
                return None, None
            val = _parse_number(parts[i])
            values.append(val)
            i += 1

    return get_master_columns(), values

def parse_boom_line_fast(data_part: str):
    if not data_part.startswith(','):
        return None, None
    parts = data_part[1:].split(',')
    if len(parts) != 36:
        return None, None
    cols = get_boom_columns()
    values = []
    for p in parts:
        p = p.strip()
        if not p:
            values.append(np.nan)
            continue
        try:
            if '.' not in p and 'e' not in p.lower():
                values.append(int(p))
                continue
            values.append(float(p))
        except ValueError:
            values.append(np.nan)
    return cols, values

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
# ...existing code...

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

    # 否则，原有逻辑：判断是 slave/boom/master/master-like 行
    data_part = rest
    if data_part.startswith(','):
        parts_len = len(data_part[1:].split(','))
        if parts_len == 142 or parts_len == 92:
            cols, vals = parse_slave_line_fast(data_part)
        elif parts_len == 36:
            cols, vals = parse_boom_line_fast(data_part)
        else:
            cols, vals = None, None
    else:
        cols, vals = parse_master_line_fast(data_part)
    return [(ts_str, cols, vals)]

# ==================== 实时监控线程 ====================
class LiveThread(QThread):
    new_data = pyqtSignal(float, dict)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, host, port, username, password, remote_path):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_path = remote_path
        self._running = False
        self.ssh = None
        self.sftp = None
        self.file = None
        self.paused = False

    def set_paused(self, paused):
        self.paused = paused

    def run(self):
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.host, port=self.port, username=self.username,
                            password=self.password, timeout=5)
            self.sftp = self.ssh.open_sftp()
            self.file = self.sftp.open(self.remote_path, 'r')
            self.file.seek(0, 2)
            self._running = True
            self.status.emit("已连接，开始实时监控...")

            last_stat = self.sftp.stat(self.remote_path)
            last_size = last_stat.st_size
            last_mtime = last_stat.st_mtime
            check_counter = 0

            last_ts_str = None  # 保存最近一个有时间戳的字符串

            while self._running:
                line = self.file.readline()
                if line:
                    line = line.strip()
                    if line:
                        results = parse_log_line(line)
                        for ts_str, cols, vals in results:
                            if cols is None or vals is None:
                                continue
                            # 优先使用本片段的 ts_str；若没有则使用上一次有时间戳的字符串
                            ts_use = ts_str if ts_str else last_ts_str
                            # 若本片段带时间戳，更新 last_ts_str
                            if ts_str:
                                last_ts_str = ts_str

                            # 解析为 epoch（若没有可用时间戳则回退到系统时间）
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
                            if not self.paused:
                                self.new_data.emit(epoch, data_dict)
                else:
                    check_counter += 1
                    if check_counter >= 5:
                        check_counter = 0
                        try:
                            new_stat = self.sftp.stat(self.remote_path)
                            if new_stat.st_size < last_size or new_stat.st_mtime > last_mtime:
                                self.file.close()
                                self.file = self.sftp.open(self.remote_path, 'r')
                                self.file.seek(0, 2)
                                last_stat = new_stat
                                last_size = new_stat.st_size
                                last_mtime = new_stat.st_mtime
                                self.status.emit("检测到日志轮转，已重新连接")
                                continue
                            last_size = new_stat.st_size
                            last_mtime = new_stat.st_mtime
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            self.error.emit(f"检查文件状态出错: {e}")
                    self.msleep(10)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.file:
                self.file.close()
            if self.sftp:
                self.sftp.close()
            if self.ssh:
                self.ssh.close()
            self._running = False

    def stop(self):
        self._running = False
        self.quit()
        self.wait()

# ==================== 后台加载线程（离线模式） ====================
try:
    import pyarrow
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False

def convert_folder_to_cache(folder_path, cache_path, progress_callback=None, stop_event=None):
    if not HAS_PARQUET:
        return False
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path)
             if os.path.isfile(os.path.join(folder_path, f)) and f != '_combined_cache.parquet']
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
    combined.to_parquet(cache_path, index=False, engine='pyarrow')
    if stop_event and stop_event.is_set():
        return False
    return True

def load_cache(cache_path):
    if not HAS_PARQUET or not os.path.exists(cache_path):
        return pd.DataFrame()
    return pd.read_parquet(cache_path, engine='pyarrow')

# ...existing code...
def load_single_log_file(filepath, progress_callback=None, stop_event=None):
    """
    逐行解析日志，针对一行可能返回多个片段（如 [ADS]:0 ... 和 [ADS]:1 ...）
    每个解析出的 (ts_str, cols, vals) 都作为单独一行，使用 dict 合并不同列名，
    最终构建 DataFrame，确保不同 model 的 ADS 列都会保留。
    """
    if stop_event and stop_event.is_set():
        return pd.DataFrame()
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return pd.DataFrame()

    rows = []           # list of dict 每个元素为一行数据（包括 timestamp）
    total = len(lines)

    for idx, raw_line in enumerate(lines):
        if stop_event and stop_event.is_set():
            return pd.DataFrame()
        line = raw_line.strip()
        if not line:
            continue

        results = parse_log_line(line)
        for ts_str, cols, vals in results:
            if cols is None or vals is None:
                continue
            if len(cols) != len(vals):
                continue
            row = {}
            # 解析时间戳为 pd.Timestamp（若有）
            if ts_str:
                try:
                    ts = pd.to_datetime(ts_str, format='%Y-%m-%d %H:%M:%S.%f', errors='coerce')
                    if pd.isna(ts):
                        ts = pd.to_datetime(ts_str, format='%Y-%m-%d %H:%M:%S', errors='coerce')
                except Exception:
                    ts = pd.NaT
            else:
                ts = pd.NaT
            row['timestamp'] = ts
            # 填充列值
            for c, v in zip(cols, vals):
                row[c] = v
            rows.append(row)

        if progress_callback and idx % 1000 == 0:
            progress_callback(idx / total if total else 0)

    if not rows:
        return pd.DataFrame()

    # 构建 DataFrame（自动合并所有列）
    df = pd.DataFrame(rows)

    # 保证 timestamp 在最前并添加 line_no
    if 'timestamp' in df.columns:
        cols = list(df.columns)
        cols.remove('timestamp')
        df = df[['timestamp'] + cols]
    df.insert(1, 'line_no', range(1, len(df)+1))

    # 将数值列转换为数值类型（保留 NaN）
    for col in df.columns:
        if col in ('timestamp', 'line_no'):
            continue
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df
# ...existing code...

class LoadThread(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal(object, bool, str)

    def __init__(self, path, use_cache, force_rebuild, use_relative_time=False):
        super().__init__()
        self.path = path
        self.use_cache = use_cache
        self.force_rebuild = force_rebuild
        self.use_relative_time = use_relative_time
        self._stop = False

    def is_set(self):
        return self._stop

    def stop_load(self):
        self._stop = True

    def run(self):
        try:
            if os.path.isfile(self.path):
                def progress_callback(p):
                    self.progress.emit(p)
                df = load_single_log_file(self.path, progress_callback, stop_event=self)
                self.finished.emit(df, self._stop, "")
                return

            if not self.use_cache:
                files = [os.path.join(self.path, f) for f in os.listdir(self.path)
                         if os.path.isfile(os.path.join(self.path, f))]
                total = len(files)
                dfs = []
                for i, fpath in enumerate(files):
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

            cache_path = os.path.join(self.path, "_combined_cache.parquet")
            cache_exists = os.path.exists(cache_path)

            if cache_exists and not self.force_rebuild:
                self.progress.emit(0.5)
                df = load_cache(cache_path)
                if df is not None and not df.empty:
                    if 'timestamp' in df.columns:
                        df['timestamp'] = pd.to_datetime(df['timestamp'])
                    self.finished.emit(df, False, "")
                    return
                self.progress.emit(0)

            def conv_progress(p):
                self.progress.emit(p)
            success = convert_folder_to_cache(self.path, cache_path, conv_progress, self)
            if not success or self._stop:
                self.finished.emit(pd.DataFrame(), True, "")
                return
            df = load_cache(cache_path)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            self.finished.emit(df, False, "")
        except Exception as e:
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
                        dt = datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc)
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
class DropPlotWidget(pg.PlotWidget):
    drop_signal = pyqtSignal(str)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.setAcceptDrops(True)

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
                item = self._drag_item
                if item.childCount() > 0:
                    for i in range(item.childCount()):
                        texts.append(item.child(i).text(0))
                else:
                    texts.append(item.text(0))
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
        self.view_width = 20.0
        self.last_update_time = 0
        self.hover_timer = None    # 节流定时器
        self.hover_pending = False
        # 垂直游标状态
        self.cursor_lines = [None, None]  # InfiniteLine 列表 [游标0(红), 游标1(蓝)]
        self.cursor_labels = []
        self.setup_ui()
        self.setup_hover()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 绘图区域
        self.plot_widget = DropPlotWidget()
        self.plot_widget.setAxisItems({'bottom': TimeAxis(orientation='bottom')})
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '数值')
        self.plot_widget.setLabel('bottom', '时间')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        self.plot_widget.addLegend()
        self.plot_widget.drop_signal.connect(self.add_curve)
        self.plot_widget.installEventFilter(self)
        self.plot_widget.mouseDoubleClickEvent = self.on_double_click
        self.plot_widget.getViewBox().sigRangeChangedManually.connect(self.on_view_range_changed)

        layout.addWidget(self.plot_widget, stretch=1)

        # 下方工具栏：跟随按钮 + 关闭按钮（靠右）
        ctrl_frame = QWidget()
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(0, 5, 0, 5)
        ctrl_layout.addStretch()
        self.follow_btn = QPushButton("🔘")
        self.follow_btn.setFixedSize(30, 25)
        self.follow_btn.setCheckable(True)
        self.follow_btn.setChecked(self.follow_latest)
        self.follow_btn.clicked.connect(self.toggle_follow)
        ctrl_layout.addWidget(self.follow_btn)
        self.close_btn = QPushButton("✖")
        self.close_btn.setFixedSize(25, 25)
        self.close_btn.setToolTip("关闭此分栏")
        self.close_btn.clicked.connect(self.request_close)
        ctrl_layout.addWidget(self.close_btn)

        layout.addWidget(ctrl_frame)

    def setup_hover(self):
        """设置鼠标悬浮数值显示"""
        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.hover_timer = QTimer()
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._process_hover)

    def on_mouse_moved(self, pos):
        if hasattr(self, 'hover_pending') and self.hover_pending:
            return
        self.hover_pending = True
        self.hover_pos = pos
        self.hover_timer.start(50)

    def _process_hover(self):
        self.hover_pending = False
        if not self.plot_widget.sceneBoundingRect().contains(self.hover_pos):
            return
        view_box = self.plot_widget.getViewBox()
        mouse_point = view_box.mapSceneToView(self.hover_pos)
        x = mouse_point.x()
        if not self.plot_items:
            self.main.statusBar().showMessage("")
            return
        best_info = None
        for col, curve in self.plot_items.items():
            if col in self.main.y_buffers:
                y_arr = np.array(self.main.y_buffers[col])
                x_arr = np.array(self.main.x_buffer)
                if len(x_arr) > len(y_arr):
                    x_arr = x_arr[-len(y_arr):]
                elif len(y_arr) > len(x_arr):
                    y_arr = y_arr[-len(x_arr):]
                if len(x_arr) == 0:
                    continue
                idx = np.argmin(np.abs(x_arr - x))
                dist = abs(x_arr[idx] - x)
                if best_info is None or dist < best_info[3]:
                    best_info = (col, x_arr[idx], y_arr[idx], dist)
            elif self.main.df is not None and col in self.main.df.columns:
                if 'timestamp' in self.main.df.columns:
                    times = self.main.df['timestamp'].astype('int64') / 1e9
                else:
                    times = self.main.df['line_no'].values
                y_arr = self.main.df[col].values
                idx = np.argmin(np.abs(times - x))
                dist = abs(times[idx] - x)
                if best_info is None or dist < best_info[3]:
                    best_info = (col, times[idx], y_arr[idx], dist)
        if best_info:
            col, x_val, y_val, _ = best_info
            try:
                dt = datetime.datetime.fromtimestamp(x_val, tz=datetime.timezone.utc)
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]
            except:
                time_str = f"{x_val:.3f}"
            msg = f"{col} | 时间: {time_str} | 数值: {y_val:.4f}"
            self.main.statusBar().showMessage(msg)
        else:
            self.main.statusBar().showMessage("")

    def eventFilter(self, obj, event):
        """拦截绘图控件的键盘事件"""
        if obj == self.plot_widget and event.type() == QEvent.KeyPress:
            tab = self.parent_tab
            if event.key() == Qt.Key_T:
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
                        tab._update_cursor_position()
                        return True
                    elif event.key() == Qt.Key_Right:
                        tab.cursor_x[ci] += step
                        tab._update_cursor_position()
                        return True
        return super().eventFilter(obj, event)

    def request_close(self):
        self.parent_tab.request_remove_subwidget(self)

    def add_curve(self, col):
        if col in self.plot_items:
            return
        if self.main.x_buffer:
            x = np.array(self.main.x_buffer)
        else:
            x = np.array([])
        if col in self.main.y_buffers:
            y = np.array(self.main.y_buffers[col])
            if len(x) > len(y):
                x = x[-len(y):]
            elif len(y) > len(x):
                y = y[-len(x):]
        elif self.main.df is not None and col in self.main.df.columns:
            y = self.main.df[col].values
            if self.main.timestamp_epoch is not None:
                x = self.main.timestamp_epoch
            elif 'timestamp' in self.main.df.columns:
                # 兜底：转换一次
                x = np.array([t.to_pydatetime().timestamp() for t in self.main.df['timestamp']])
            else:
                x = self.main.df['line_no'].values
            mask = ~np.isnan(y)
            x = x[mask] if len(x) == len(y) else x
            y = y[mask]
        else:
            return
        if len(y) == 0 or np.all(np.isnan(y)):
            return
        color = self._next_color()
        pen = pg.mkPen(color=color, width=2.5)
        opts = {'pen': pen, 'name': col, 'antialias': False, 'downsample': 300, 'autoDownsample': True}
        curve = self.plot_widget.plot(x, y, **opts)
        self.plot_items[col] = curve
        # 如果游标已激活，为新曲线添加标注
        for ci in range(2):
            if self.parent_tab.cursor_enabled[ci] and self.parent_tab.cursor_x[ci] is not None:
                self.update_cursor_annotations(self.parent_tab.cursor_x[ci], cursor_idx=ci)
        if self.follow_latest and self.main.x_buffer:
            self.scroll_to_latest()
        self.parent_tab._align_left_axes()

    def update_curves(self):
        if not self.main.x_buffer:
            return
        x_arr = np.array(self.main.x_buffer)
        for col, curve in list(self.plot_items.items()):
            if col in self.main.y_buffers:
                y_arr = np.array(self.main.y_buffers[col])
                if len(x_arr) > len(y_arr):
                    x_use = x_arr[-len(y_arr):]
                elif len(y_arr) > len(x_arr):
                    y_arr = y_arr[-len(x_arr):]
                    x_use = x_arr
                else:
                    x_use = x_arr
                curve.setData(x_use, y_arr)
        if self.follow_latest and self.main.x_buffer:
            self.scroll_to_latest()

    def scroll_to_latest(self):
        if not self.main.x_buffer:
            return
        view_box = self.plot_widget.getViewBox()
        current_range = view_box.viewRange()[0]
        width = current_range[1] - current_range[0]
        if width <= 0 or width > 1e9:
            width = self.view_width
        latest_x = self.main.x_buffer[-1]
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
                x_full = np.array(self.main.x_buffer)
                if len(x_full) > len(y_full):
                    x_full = x_full[-len(y_full):]
                elif len(y_full) > len(x_full):
                    y_full = y_full[-len(x_full):]
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
        if checked and self.main.x_buffer:
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

    def update_cursor_annotations(self, x, cursor_idx=0):
        """创建/更新游标与曲线交点的数值标注"""
        self._remove_cursor_labels()
        self._add_cursor_time_label(x, cursor_idx)
        if not self.plot_items:
            return

        view_box = self.plot_widget.getViewBox()
        x_range = view_box.viewRange()[0]
        x_width = x_range[1] - x_range[0]
        x_offset = x_width * 0.01 if x_width > 0 else 0.01

        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        for idx, (col, curve) in enumerate(self.plot_items.items()):
            y_val = None
            if col in self.main.y_buffers:
                y_arr = np.array(self.main.y_buffers[col])
                x_arr = np.array(self.main.x_buffer)
                if len(x_arr) > len(y_arr):
                    x_arr = x_arr[-len(y_arr):]
                elif len(y_arr) > len(x_arr):
                    y_arr = y_arr[-len(x_arr):]
                if len(x_arr) > 0:
                    i = np.argmin(np.abs(x_arr - x))
                    y_val = y_arr[i]
            elif self.main.df is not None and col in self.main.df.columns:
                if self.main.timestamp_epoch is not None:
                    x_arr = self.main.timestamp_epoch
                elif 'timestamp' in self.main.df.columns:
                    x_arr = np.array([t.to_pydatetime().timestamp()
                                      for t in self.main.df['timestamp']])
                else:
                    x_arr = self.main.df['line_no'].values
                y_arr = self.main.df[col].values
                mask = ~np.isnan(y_arr)
                if len(x_arr) == len(y_arr):
                    x_arr = x_arr[mask]
                    y_arr = y_arr[mask]
                if len(y_arr) > 0:
                    i = np.argmin(np.abs(x_arr - x))
                    y_val = y_arr[i]

            if y_val is None or (isinstance(y_val, float) and np.isnan(y_val)):
                continue

            text = f"{col}={y_val:.4f}"
            color = colors[idx % len(colors)]
            label = pg.TextItem(text=text, anchor=(0, 0.5), color=color)
            label.setPos(x + x_offset, y_val)
            self.plot_widget.addItem(label)
            self.cursor_labels.append(label)

    def _remove_cursor_labels(self):
        """移除所有数值标注"""
        for label in self.cursor_labels:
            self.plot_widget.removeItem(label)
        self.cursor_labels.clear()

    def _add_cursor_time_label(self, x, cursor_idx=0):
        """在游标线顶部添加时间标注"""
        try:
            dt = datetime.datetime.fromtimestamp(x, tz=datetime.timezone.utc)
            time_str = dt.strftime("%H:%M:%S.%f")[:-3]
        except Exception:
            time_str = f"{x:.3f}"
        # 获取视图Y范围顶部位置
        view_box = self.plot_widget.getViewBox()
        y_range = view_box.viewRange()[1]
        y_top = y_range[1] - (y_range[1] - y_range[0]) * 0.02
        color = self.CURSOR_COLORS[cursor_idx]
        label = pg.TextItem(text=f"t={time_str}", anchor=(0, 1), color=color)
        label.setPos(x, y_top)
        self.plot_widget.addItem(label)
        self.cursor_labels.append(label)

    def clear_all_curves(self):
        self._remove_cursor_labels()
        for curve in self.plot_items.values():
            self.plot_widget.removeItem(curve)
        self.plot_items.clear()

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
        self._align_left_axes()

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
        index = self.sub_widgets.index(sub_widget)
        self.sub_widgets.pop(index)
        widget_to_remove = self.splitter.widget(index)
        widget_to_remove.deleteLater()

    def sync_scroll_to_latest(self, source_width=None):
        """同步所有子图的 X 轴到最新数据点，并开启跟随"""
        if not self.sub_widgets:
            return
        # 确定使用的 X 轴跨度宽度：如果提供了 source_width 则使用，否则取所有子图宽度的最大值
        if source_width is not None and source_width > 0:
            width = source_width
        else:
            widths = [sub.view_width for sub in self.sub_widgets if sub.view_width > 0]
            width = max(widths) if widths else 20.0
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
        """键盘移动游标后更新所有子图的线条和标注"""
        ci = self.active_cursor
        if not self.cursor_enabled[ci] or self.cursor_x[ci] is None:
            return
        for sub in self.sub_widgets:
            if sub.cursor_lines[ci] is not None:
                sub.cursor_lines[ci].blockSignals(True)
                sub.cursor_lines[ci].setPos(self.cursor_x[ci])
                sub.cursor_lines[ci].blockSignals(False)
            sub.update_cursor_annotations(self.cursor_x[ci], cursor_idx=ci)

    def _align_left_axes(self):
        """对齐所有子视图的左轴宽度（垂直分栏时排版对齐）"""
        if len(self.sub_widgets) < 2:
            return
        # 先重置为自动宽度，让各轴重新计算
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

# ==================== 主窗口 ====================
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
        win_width = int(screen_width * 0.7)
        win_height = int(screen_height * 0.8)
        # 确保最小尺寸，避免界面元素挤压
        win_width = max(win_width, 1000)
        win_height = max(win_height, 800)

        self.resize(win_width, win_height)
        self.setMinimumSize(1000, 800)   # 允许用户手动缩小但不能小于此尺寸
        self.setWindowTitle("YC日志分析平台")
        self.df = None
        self.current_columns = []
        self.load_thread = None
        self.live_thread = None
        self.use_cache = True
        self.force_rebuild = False
        self.timestamp_epoch = None

        self.buffer_seconds = 40
        self.buffer_points = 40000
        self.buffer_size = self.buffer_points
        self.x_buffer = deque(maxlen=self.buffer_size)
        self.y_buffers = {}
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
        left_panel = QWidget()
        left_panel.setFixedWidth(480)
        left_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("📊 YC日志分析平台")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; margin-bottom: 5px;")
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
        path_layout.addWidget(self.path_edit)
        btn_layout = QHBoxLayout()
        self.file_btn = QPushButton("选择文件")
        self.file_btn.clicked.connect(self.select_file)
        self.folder_btn = QPushButton("选择文件夹")
        self.folder_btn.clicked.connect(self.select_folder)
        self.load_btn = QPushButton("加载")
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
        self.relative_time_cb.setToolTip("忽略日志原始时间戳")
        opt_layout.addWidget(self.relative_time_cb)
        opt_group.setLayout(opt_layout)
        offline_layout.addWidget(opt_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.cancel_load)
        self.cancel_btn.setEnabled(False)
        offline_layout.addWidget(self.progress_bar)
        offline_layout.addWidget(self.cancel_btn)

        self.info_label = QLabel("未加载数据")
        self.info_label.setWordWrap(True)
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
        self.device_type.addItems(["从臂", "主手", "boom", "ADS"])
        self.device_type.currentTextChanged.connect(self.on_device_type_changed)
        dev_type_layout.addWidget(self.device_type)
        dev_type_layout.addWidget(QLabel("编号/手别:"))
        self.device_index = QComboBox()
        dev_type_layout.addWidget(self.device_index)
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
        self.connect_btn.clicked.connect(self.start_live)
        self.stop_live_btn = QPushButton("停止监控")
        self.stop_live_btn.setEnabled(False)
        self.stop_live_btn.clicked.connect(self.stop_live)
        monitor_layout.addWidget(self.connect_btn)
        monitor_layout.addWidget(self.stop_live_btn)
        online_layout.addLayout(monitor_layout)

        pause_layout = QHBoxLayout()
        self.pause_btn = QPushButton("⏸️ 暂停")
        self.pause_btn.clicked.connect(self.pause_live)
        self.pause_btn.setEnabled(False)
        self.resume_btn = QPushButton("▶️ 继续")
        self.resume_btn.clicked.connect(self.resume_live)
        self.resume_btn.setEnabled(False)
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
        self.buffer_spin.valueChanged.connect(self.on_buffer_size_changed)
        buffer_layout.addWidget(self.buffer_spin)
        buffer_group.setLayout(buffer_layout)
        online_layout.addWidget(buffer_group)

        self.online_info_label = QLabel("未连接")
        self.online_info_label.setWordWrap(True)
        online_layout.addWidget(self.online_info_label)
        self.device_index.currentTextChanged.connect(self.on_device_index_changed)

        online_layout.addStretch()
        self.stacked_widget.addWidget(online_widget)

        self.update_device_index()

        # 数据列树（支持拖拽）
        left_layout.addWidget(QLabel("📋 数据列"))
        self.tree = DragTreeWidget()
        self.tree.setHeaderLabel("数据列")
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setIndentation(20)
        self.tree.setMinimumHeight(400)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        left_layout.addWidget(self.tree)

        # 清除当前页所有曲线按钮
        clear_btn = QPushButton("🗑️ 清除当前页所有曲线")
        clear_btn.clicked.connect(self.clear_current_tab_curves)
        left_layout.addWidget(clear_btn)

        self.save_btn = QPushButton("💾 保存当前页图像")
        self.save_btn.clicked.connect(self.save_current_figure)
        left_layout.addWidget(self.save_btn)

        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # ========== 右侧绘图区域 (QTabWidget) ==========
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)

        # 右上角工具栏按钮组
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(2)

        # 水平分栏按钮（图标）
        self.h_split_btn = QPushButton("‖")
        # self.h_split_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMaxButton))
        self.h_split_btn.setToolTip("水平分栏")
        self.h_split_btn.setFixedSize(30, 30)
        self.h_split_btn.clicked.connect(self.split_current_tab_horizontal)
        corner_layout.addWidget(self.h_split_btn)

        # 垂直分栏按钮
        self.v_split_btn = QPushButton("☰")
        # self.v_split_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMinButton))
        self.v_split_btn.setToolTip("垂直分栏")
        self.v_split_btn.setFixedSize(30, 30)
        self.v_split_btn.clicked.connect(self.split_current_tab_vertical)
        corner_layout.addWidget(self.v_split_btn)

        # 新建标签页按钮
        self.new_tab_btn = QPushButton("+")
        self.new_tab_btn.setFixedSize(30, 30)
        self.new_tab_btn.clicked.connect(self.new_plot_tab)
        corner_layout.addWidget(self.new_tab_btn)

        # 垂直游标切换按钮
        self.cursor_btn = QPushButton("I")
        self.cursor_btn.setToolTip("切换游标A (Tab键切换活动游标, 左右箭头移动)")
        self.cursor_btn.setFixedSize(30, 30)
        self.cursor_btn.setCheckable(True)
        self.cursor_btn.clicked.connect(lambda: self.toggle_current_tab_cursor(0))
        corner_layout.addWidget(self.cursor_btn)

        self.cursor2_btn = QPushButton("II")
        self.cursor2_btn.setToolTip("切换游标B (Tab键切换活动游标, 左右箭头移动)")
        self.cursor2_btn.setFixedSize(30, 30)
        self.cursor2_btn.setCheckable(True)
        self.cursor2_btn.clicked.connect(lambda: self.toggle_current_tab_cursor(1))
        corner_layout.addWidget(self.cursor2_btn)

        self.tab_widget.setCornerWidget(corner_widget, Qt.TopRightCorner)

        self.default_tab = PlotTab(self, "绘图1")
        self.tab_widget.addTab(self.default_tab, "绘图1")
        self.tab_widget.currentChanged.connect(self._on_plot_tab_changed)
        main_layout.addWidget(self.tab_widget, stretch=1)

    # ========== 标签页管理 ==========
    def new_plot_tab(self):
        count = self.tab_widget.count() + 1
        new_tab = PlotTab(self, f"绘图{count}")
        self.tab_widget.addTab(new_tab, f"绘图{count}")
        self.tab_widget.setCurrentWidget(new_tab)

    def close_tab(self, index):
        if self.tab_widget.count() <= 1:
            QMessageBox.information(self, "提示", "至少需要保留一个标签页")
            return
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        widget.deleteLater()

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
        tab = self.tab_widget.widget(index)
        if isinstance(tab, PlotTab):
            self.cursor_btn.setChecked(tab.cursor_enabled[0])
            self.cursor2_btn.setChecked(tab.cursor_enabled[1])

    def save_current_figure(self):
        current_tab = self.tab_widget.currentWidget()
        if not current_tab or not current_tab.sub_widgets:
            QMessageBox.information(self, "提示", "当前标签页没有曲线可保存")
            return
        # 只保存第一个子图（或其他逻辑）
        first_sub = current_tab.sub_widgets[0]
        if not first_sub.plot_items:
            QMessageBox.information(self, "提示", "当前标签页没有曲线可保存")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存图像", "",
                                            "PNG图片 (*.png);;JPEG图片 (*.jpg);;BMP图片 (*.bmp)")
        if path:
            pixmap = first_sub.plot_widget.grab()
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
    def update_device_index(self):
        self.device_index.clear()
        dev_type = self.device_type.currentText()
        if dev_type == "从臂":
            for i in range(1, 5):
                self.device_index.addItem(f"{i}")
        elif dev_type == "主手":
            self.device_index.addItem("左")
            self.device_index.addItem("右")
        elif dev_type == "ADS":
            self.device_index.addItem("ADS")
        else:
            self.device_index.addItem("boom")
        self._update_remote_path()

    def on_device_type_changed(self):
        if self.live_thread is not None and self.live_thread.isRunning():
            self.stop_live()
            QMessageBox.information(self, "提示", "设备类型已更改，已停止当前监控。请重新连接。")
        self.update_device_index()

    def on_device_index_changed(self):
        if self.live_thread is not None and self.live_thread.isRunning():
            self.stop_live()
            QMessageBox.information(self, "提示", "设备编号已更改，已停止当前监控。请重新连接。")
        self._update_remote_path()

    def on_buffer_size_changed(self, new_seconds):
        if new_seconds == self.buffer_seconds:
            return
        self.buffer_seconds = new_seconds
        new_points = new_seconds * 1000
        new_points = max(1000, min(120000, new_points))
        old_x = self.x_buffer
        new_x = deque(maxlen=new_points)
        new_x.extend(old_x)
        self.x_buffer = new_x
        new_y_buffers = {}
        for col, ybuf in self.y_buffers.items():
            new_ybuf = deque(maxlen=new_points)
            new_ybuf.extend(ybuf)
            new_y_buffers[col] = new_ybuf
        self.y_buffers = new_y_buffers
        self.buffer_size = new_points
        self.statusBar().showMessage(f"保留时间已调整为 {new_seconds} s")

    def _update_remote_path(self):
        dev_type = self.device_type.currentText()
        idx = self.device_index.currentText()
        if dev_type == "从臂":
            self.current_remote_path = f"/data/log/rt/mmsArm{idx}/mmsArm{idx}"
        elif dev_type == "主手":
            if idx == "左":
                self.current_remote_path = "/data/log/rt/LeftDataModel/LeftDataModel"
            else:
                self.current_remote_path = "/data/log/rt/RightDataModel/RightDataModel"
        elif dev_type == "ADS":
            self.current_remote_path = "/data/log/rt/LOUT/LOUT"
        else:
            self.current_remote_path = "/data/log/rt/mmsBoom/mmsBoom"

    def clear_online_data(self):
        self.x_buffer.clear()
        self.y_buffers.clear()
        self.current_columns.clear()
        self.tree.clear()
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'clear_all_curves'):
                tab.clear_all_curves()

    def pause_live(self):
        if self.live_thread and self.live_thread.isRunning():
            self.live_thread.set_paused(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.statusBar().showMessage("实时监控已暂停")

    def resume_live(self):
        if self.live_thread and self.live_thread.isRunning():
            self.live_thread.set_paused(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.statusBar().showMessage("实时监控已恢复")

    # ========== 在线监控 ==========
    def start_live(self):
        self.clear_online_data()
        ip = self.ip_edit.text().strip()
        port = int(self.port_edit.text().strip())
        user = self.user_edit.text().strip()
        pwd = self.passwd_edit.text().strip()
        self._update_remote_path()
        remote_path = self.current_remote_path

        if not ip or not user or not remote_path:
            QMessageBox.warning(self, "错误", "请填写完整的主机、用户名，并确保设备类型/编号正确")
            return

        self.x_buffer.clear()
        self.y_buffers.clear()

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'follow_latest'):
                for sub in tab.sub_widgets:
                    sub.follow_latest = False
                    sub.follow_btn.setChecked(False)

        self.live_thread = LiveThread(ip, port, user, pwd, remote_path)
        self.live_thread.new_data.connect(self.on_new_data)
        self.live_thread.error.connect(self.on_live_error)
        self.live_thread.status.connect(self.statusBar().showMessage)
        self.live_thread.start()

        self.connect_btn.setEnabled(False)
        self.stop_live_btn.setEnabled(True)
        self.update_timer.start()
        self.online_info_label.setText("正在监控中...")
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)

    def stop_live(self):
        if self.live_thread:
            self.live_thread.stop()
            self.live_thread = None
        self.update_timer.stop()
        self.connect_btn.setEnabled(True)
        self.stop_live_btn.setEnabled(False)
        self.online_info_label.setText("未连接")
        self.statusBar().showMessage("实时监控已停止")
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)

    def on_new_data(self, epoch, data_dict):
        self.x_buffer.append(epoch)
        for col, val in data_dict.items():
            if col not in self.y_buffers:
                self.y_buffers[col] = deque(maxlen=self.buffer_size)
            self.y_buffers[col].append(val)
        # 自动添加新列到树中（如果不存在）
        for col in data_dict.keys():
            if col not in self.current_columns:
                self.current_columns.append(col)
                # 判断是否为 LOUT 格式的列名（包含下划线且第一部分是数字）
                if '_' in col and col.split('_')[0].isdigit():
                    model = col.split('_')[0]
                    var = model   # 父节点显示为 model 号
                    # 子节点列名保持全名
                else:
                    # 原有处理
                    if '[' in col and ']' in col:
                        var = col.split('[')[0]
                    elif '_' in col and col.split('_')[-1].isdigit():
                        parts = col.rsplit('_', 1)
                        var = parts[0]
                    else:
                        var = col
                # 查找父节点
                found = False
                for i in range(self.tree.topLevelItemCount()):
                    if self.tree.topLevelItem(i).text(0) == var:
                        parent = self.tree.topLevelItem(i)
                        found = True
                        break
                if not found:
                    parent = QTreeWidgetItem(self.tree)
                    parent.setText(0, var)
                # 添加子节点
                child = QTreeWidgetItem(parent)
                child.setText(0, col)
                child.setToolTip(0, col)

    def update_plots_from_buffer(self):
        if not self.x_buffer:
            return
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'update_curves'):
                tab.update_curves()

    def on_live_error(self, err):
        QMessageBox.critical(self, "实时监控错误", err)
        self.stop_live()

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
        cache_path = os.path.join(folder, "_combined_cache.parquet")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        self.force_rebuild = True
        self.start_load()

    def start_load(self):
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
                                      use_relative_time=self.relative_time_cb.isChecked())
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
            if 'timestamp' in df.columns and df['timestamp'].notna().any():
                try:
                    # 使用列表推导，跳过 NaT
                    self.timestamp_epoch = np.array([t.timestamp() if pd.notna(t) else np.nan for t in df['timestamp']])
                except Exception as e:
                    print(f"时间戳转换失败: {e}")
                    self.timestamp_epoch = None
            else:
                self.timestamp_epoch = None

            # 如果勾选了相对时间，以第一个时间戳为基准，按行号生成时间轴（忽略原始时间戳间隔）
            if self.relative_time_cb.isChecked() and 'line_no' in df.columns:
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
                for col in sorted(group_dict[var]):
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
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "加载错误", f"发生异常：{str(e)}\n请检查日志文件格式或尝试减少文件数量。")
            self.info_label.setText("加载失败")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()