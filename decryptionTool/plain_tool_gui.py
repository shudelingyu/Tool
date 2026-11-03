import re
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

import copy_to_plain
import restore_from_plain

MANIFEST_NAME = 'plain_copy_map.json'
SUFFIX_RE = re.compile(r'^\.([A-Za-z0-9_-]{1,32})$')


class SignalStream:
    """把脚本内的 print 输出转成 Qt 信号，供界面实时显示"""

    def __init__(self, emit):
        self._emit = emit

    def write(self, text):
        if text:
            self._emit(text)
        return len(text)

    def flush(self):
        pass


class ScriptWorker(QThread):
    """在后台线程里执行脚本逻辑，避免阻塞界面，打包后也无需外部 Python"""

    output = pyqtSignal(str)
    done = pyqtSignal(int)

    def __init__(self, runner, argv, should_stop, parent=None):
        super().__init__(parent)
        self._runner = runner
        self._argv = argv
        self._should_stop = should_stop

    def run(self):
        stream = SignalStream(self.output.emit)
        code = 1
        try:
            with redirect_stdout(stream), redirect_stderr(stream):
                code = self._runner(self._argv, should_stop=self._should_stop)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception:
            traceback.print_exc()
            code = 1
        self.done.emit(code)

STYLE = """
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}
QLabel#appTitle { font-size: 16pt; font-weight: 600; color: #0F172A; }
QLabel#appSubtitle { font-size: 10pt; color: #64748B; }
QLabel#sectionTitle { font-size: 11pt; font-weight: 600; color: #0F172A; }
QLabel#fieldLabel { font-size: 9pt; color: #475569; }
QLabel#hintLabel { font-size: 9pt; color: #94A3B8; }
QLabel#summaryLabel { font-size: 9pt; color: #64748B; }

QLabel#statusChip { border-radius: 10px; padding: 4px 12px; font-size: 9pt; font-weight: 600; }
QLabel#statusChip[state="ready"] { background: #F1F5F9; color: #475569; }
QLabel#statusChip[state="running"] { background: #EFF6FF; color: #1D4ED8; }
QLabel#statusChip[state="success"] { background: #ECFDF5; color: #15803D; }
QLabel#statusChip[state="error"] { background: #FEF2F2; color: #B91C1C; }

QFrame#dropZone {
    background: #F8FAFC;
    border: 2px dashed #CBD5E1;
    border-radius: 10px;
}
QFrame#dropZone[dragging="true"] {
    background: #EFF6FF;
    border: 2px dashed #2563EB;
}
QFrame#dropZone[loaded="true"] {
    background: #F0FDF4;
    border: 2px solid #86EFAC;
}
QLabel#dropTitle { font-size: 11pt; font-weight: 600; color: #334155; background: transparent; }
QLabel#dropHint { font-size: 9pt; color: #94A3B8; background: transparent; }
QFrame#dropZone[dragging="true"] QLabel#dropTitle { color: #1D4ED8; }
QFrame#dropZone[dragging="true"] QLabel#dropHint { color: #2563EB; }
QFrame#dropZone[loaded="true"] QLabel#dropTitle { color: #15803D; }

QFrame#actionBar { background: transparent; border: none; }

QLineEdit {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 9.5pt;
    color: #0F172A;
}
QLineEdit:read-only { background: #F8FAFC; color: #334155; }
QLineEdit:focus { border: 1px solid #2563EB; }
QLineEdit:disabled { background: #F1F5F9; color: #94A3B8; }

QCheckBox { font-size: 9.5pt; color: #334155; spacing: 8px; }
QCheckBox:disabled { color: #94A3B8; }

QPushButton { border-radius: 8px; padding: 7px 16px; font-size: 9.5pt; font-weight: 500; }
QPushButton#primary { background: #2563EB; color: #FFFFFF; border: 1px solid #2563EB; }
QPushButton#primary:hover { background: #1D4ED8; border-color: #1D4ED8; }
QPushButton#primary:pressed { background: #1E40AF; }
QPushButton#primary:disabled { background: #BFDBFE; border-color: #BFDBFE; color: #EFF6FF; }
QPushButton#secondary { background: #FFFFFF; color: #334155; border: 1px solid #CBD5E1; }
QPushButton#secondary:hover { background: #F1F5F9; border-color: #94A3B8; }
QPushButton#secondary:pressed { background: #E2E8F0; }
QPushButton#secondary:disabled { background: #F8FAFC; color: #94A3B8; border-color: #E2E8F0; }
QPushButton#ghost { background: transparent; color: #2563EB; border: none; padding: 5px 10px; }
QPushButton#ghost:hover { background: #EFF6FF; }
QPushButton#ghost:disabled { color: #93C5FD; background: transparent; }
QPushButton#danger { background: #FFFFFF; color: #DC2626; border: 1px solid #FECACA; }
QPushButton#danger:hover { background: #FEF2F2; border-color: #FCA5A5; }
QPushButton#danger:disabled { color: #FCA5A5; border-color: #FEE2E2; background: #FFFFFF; }

QProgressBar { border: none; background: #E2E8F0; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: #2563EB; border-radius: 4px; }

QPlainTextEdit#log {
    background: #0F172A;
    border: 1px solid #1E293B;
    border-radius: 10px;
    padding: 10px;
    color: #E2E8F0;
    selection-background-color: #334155;
}

QScrollArea { background: transparent; border: none; }
QWidget#settingsContainer { background: transparent; }
QSplitter::handle:vertical { background: transparent; height: 10px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QToolTip { background: #0F172A; color: #F8FAFC; border: 1px solid #334155; padding: 6px; }
"""


class DropZone(QFrame):
    """文件夹拖拽区域：拖入高亮、离开恢复、松开后发出路径"""

    folderDropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('dropZone')
        self.setAcceptDrops(True)
        self.setProperty('dragging', 'false')
        self.setProperty('loaded', 'false')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(92)
        self._path_text = ''

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.title_label = QLabel('拖拽文件夹到此处')
        self.title_label.setObjectName('dropTitle')
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.hint_label = QLabel('支持从文件资源管理器直接拖入，松开即可导入')
        self.hint_label.setObjectName('dropHint')
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_loaded(self, loaded, path=''):
        self._path_text = path if loaded else ''
        self.setProperty('loaded', 'true' if loaded else 'false')
        self._repolish()
        if loaded:
            self.title_label.setText('已选择文件夹')
            self.hint_label.setText(self._path_text)
            self.setToolTip(self._path_text)
        else:
            self.title_label.setText('拖拽文件夹到此处')
            self.hint_label.setText('支持从文件资源管理器直接拖入，松开即可导入')
            self.setToolTip('')

    def _set_dragging(self, dragging):
        self.setProperty('dragging', 'true' if dragging else 'false')
        self._repolish()
        if dragging:
            self.title_label.setText('松开鼠标，导入此文件夹')
            self.hint_label.setText('已识别到文件夹，松开即可完成选择')
        elif self.property('loaded') == 'true':
            self.title_label.setText('已选择文件夹')
            self.hint_label.setText(self._path_text)
        else:
            self.title_label.setText('拖拽文件夹到此处')
            self.hint_label.setText('支持从文件资源管理器直接拖入，松开即可导入')

    @staticmethod
    def _first_folder(mime_data):
        for url in mime_data.urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                return str(path)
        return None

    def dragEnterEvent(self, event):
        if self._first_folder(event.mimeData()):
            event.acceptProposedAction()
            self._set_dragging(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._first_folder(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_dragging(False)
        event.accept()

    def dropEvent(self, event):
        self._set_dragging(False)
        folder = self._first_folder(event.mimeData())
        if folder:
            event.acceptProposedAction()
            self.folderDropped.emit(folder)
        else:
            event.ignore()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('root')
        self.setWindowTitle('Plain Tool · 本地文件转换与还原')
        self.resize(1020, 760)
        self.setMinimumSize(820, 620)

        self.folder = None
        self._running = False
        self._stopped = False
        self._pending_output = ''
        self._sizes_applied = False
        self._stop_event = threading.Event()
        self.worker = None

        self._build_ui()
        self._set_status('ready', '就绪')
        self._append_log('就绪 · 拖入文件夹或点击「选择文件夹」开始', '#94A3B8')

    # ---------- 界面构建 ----------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        title = QLabel('Plain Tool')
        title.setObjectName('appTitle')
        subtitle = QLabel('把受控文件转换为明文副本，或按映射清单还原原始后缀')
        subtitle.setObjectName('appSubtitle')

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(title)
        header.addWidget(subtitle)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        settings_container = QWidget()
        settings_container.setObjectName('settingsContainer')
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)
        settings_layout.addWidget(self._build_folder_card())
        settings_layout.addWidget(self._build_action_card())
        settings_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(settings_container)

        settings_pane = QWidget()
        pane_layout = QVBoxLayout(settings_pane)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        pane_layout.setSpacing(8)
        pane_layout.addWidget(scroll, 1)
        pane_layout.addWidget(self._build_button_bar())

        splitter.addWidget(settings_pane)
        splitter.addWidget(self._build_log_card())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 200])
        self.splitter = splitter

        outer.addWidget(splitter, 1)

    def _build_folder_card(self):
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel('目标文件夹')
        title.setObjectName('sectionTitle')
        hint = QLabel('必填')
        hint.setObjectName('hintLabel')
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(hint)
        layout.addLayout(title_row)

        self.drop_zone = DropZone()
        self.drop_zone.folderDropped.connect(self._set_folder)
        layout.addWidget(self.drop_zone)

        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        path_label = QLabel('当前路径')
        path_label.setObjectName('fieldLabel')
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText('尚未选择文件夹')
        self.path_edit.setToolTip('已选择的文件夹完整路径')
        self.path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.browse_btn = QPushButton('选择文件夹')
        self.browse_btn.setObjectName('secondary')
        self.browse_btn.setToolTip('打开系统对话框手动选择文件夹')
        self.browse_btn.clicked.connect(self._choose_folder)

        self.clear_btn = QPushButton('清空')
        self.clear_btn.setObjectName('ghost')
        self.clear_btn.setToolTip('清除当前选择的文件夹')
        self.clear_btn.clicked.connect(self._clear_folder)

        path_row.addWidget(path_label)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_btn)
        path_row.addWidget(self.clear_btn)
        layout.addLayout(path_row)
        return card

    def _build_action_card(self):
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        title = QLabel('操作设置')
        title.setObjectName('sectionTitle')
        layout.addWidget(title)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        label1 = QLabel('转换目标后缀')
        label1.setObjectName('fieldLabel')
        self.suffix_edit = QLineEdit('urdf')
        self.suffix_edit.setFixedWidth(110)
        self.suffix_edit.setToolTip('直接替换原文件后缀，例如 hxx → urdf')
        self.suffix_edit.setPlaceholderText('如 urdf')
        hint1 = QLabel('直接替换原后缀，不追加')
        hint1.setObjectName('hintLabel')
        self.delete_checkbox = QCheckBox('转换后删除原文件')
        self.delete_checkbox.setChecked(True)
        self.delete_checkbox.setToolTip('默认删除源文件；取消勾选则保留源文件')
        row1.addWidget(label1)
        row1.addWidget(self.suffix_edit)
        row1.addWidget(hint1)
        row1.addStretch(1)
        row1.addWidget(self.delete_checkbox)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        label2 = QLabel('按后缀还原')
        label2.setObjectName('fieldLabel')
        self.from_edit = QLineEdit('urdf')
        self.from_edit.setFixedWidth(96)
        self.from_edit.setToolTip('当前文件的统一后缀')
        self.from_edit.setPlaceholderText('当前后缀')
        arrow = QLabel('→')
        arrow.setObjectName('hintLabel')
        self.to_edit = QLineEdit('hxx')
        self.to_edit.setFixedWidth(96)
        self.to_edit.setToolTip('要还原成的原始后缀')
        self.to_edit.setPlaceholderText('原始后缀')
        self.overwrite_checkbox = QCheckBox('覆盖已存在的目标文件')
        self.overwrite_checkbox.setToolTip('不勾选时，目标文件已存在则跳过')
        row2.addWidget(label2)
        row2.addWidget(self.from_edit)
        row2.addWidget(arrow)
        row2.addWidget(self.to_edit)
        row2.addStretch(1)
        row2.addWidget(self.overwrite_checkbox)
        layout.addLayout(row2)
        return card

    def _build_button_bar(self):
        bar = QFrame()
        bar.setObjectName('actionBar')
        button_row = QHBoxLayout(bar)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)

        self.convert_btn = QPushButton('开始转换')
        self.convert_btn.setObjectName('primary')
        self.convert_btn.setToolTip('按目标后缀生成明文副本（可选保留或删除原文件）')
        self.convert_btn.clicked.connect(self._start_convert)

        self.restore_manifest_btn = QPushButton('按清单还原')
        self.restore_manifest_btn.setObjectName('secondary')
        self.restore_manifest_btn.setToolTip('读取 plain_copy_map.json，精确还原每个文件的原始后缀')
        self.restore_manifest_btn.clicked.connect(self._start_restore_manifest)

        self.restore_suffix_btn = QPushButton('按后缀还原')
        self.restore_suffix_btn.setObjectName('secondary')
        self.restore_suffix_btn.setToolTip('把目录内所有指定后缀的文件统一改为原始后缀')
        self.restore_suffix_btn.clicked.connect(self._start_restore_suffix)

        self.stop_btn = QPushButton('停止')
        self.stop_btn.setObjectName('danger')
        self.stop_btn.setToolTip('终止当前正在运行的脚本')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_process)

        button_row.addWidget(self.convert_btn)
        button_row.addWidget(self.restore_manifest_btn)
        button_row.addWidget(self.restore_suffix_btn)
        button_row.addStretch(1)
        button_row.addWidget(self.stop_btn)
        return bar

    def _build_log_card(self):
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel('运行日志')
        title.setObjectName('sectionTitle')
        self.status_chip = QLabel('就绪')
        self.status_chip.setObjectName('statusChip')
        self.status_chip.setProperty('state', 'ready')
        self.summary_label = QLabel('')
        self.summary_label.setObjectName('summaryLabel')
        self.summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)

        self.clear_log_btn = QPushButton('清空日志')
        self.clear_log_btn.setObjectName('ghost')
        self.clear_log_btn.setToolTip('清空下方的运行日志')
        self.clear_log_btn.clicked.connect(lambda: self.log.clear())

        header.addWidget(title)
        header.addWidget(self.status_chip)
        header.addWidget(self.summary_label, 1)
        header.addWidget(self.progress)
        header.addWidget(self.clear_log_btn)
        layout.addLayout(header)

        self.log = QPlainTextEdit()
        self.log.setObjectName('log')
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(110)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log.setFont(QFont('Consolas', 10))
        layout.addWidget(self.log, 1)
        return card

    # ---------- 进程与日志 ----------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._sizes_applied:
            self._sizes_applied = True
            QTimer.singleShot(0, lambda: self.splitter.setSizes([450, 200]))

    def _append_log(self, text, color='#E2E8F0'):
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        time_format = QTextCharFormat()
        time_format.setForeground(QColor('#64748B'))
        cursor.insertText(datetime.now().strftime('%H:%M:%S') + '  ', time_format)
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        cursor.insertText(text + '\n', text_format)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _line_color(self, line):
        if '失败' in line or '错误' in line or 'Traceback' in line:
            return '#F87171'
        if '跳过' in line:
            return '#94A3B8'
        if '已转换' in line or '已恢复' in line or '已删除' in line:
            return '#4ADE80'
        if line.startswith('完成') or '全部恢复完成' in line:
            return '#93C5FD'
        if line.startswith('映射清单'):
            return '#7DD3FC'
        return '#E2E8F0'

    def _on_script_output(self, text):
        self._pending_output += text
        while '\n' in self._pending_output:
            line, self._pending_output = self._pending_output.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                continue
            self._append_log(line, self._line_color(line))
            if line.startswith('完成') or '全部恢复完成' in line:
                self.summary_label.setText(line.strip())

    def _on_script_finished(self, exit_code):
        if self._pending_output.strip():
            self._append_log(self._pending_output.strip(), self._line_color(self._pending_output))
            self._pending_output = ''
        self._set_running(False)
        if self._stopped:
            self._stopped = False
            self._set_status('ready', '已停止')
            return
        if exit_code == 0:
            self._set_status('success', '完成')
        else:
            self._set_status('error', f'失败（退出码 {exit_code}）')

    def _set_running(self, running):
        self._running = running
        for widget in (self.convert_btn, self.restore_manifest_btn, self.restore_suffix_btn,
                       self.browse_btn, self.clear_btn):
            widget.setEnabled(not running)
        for widget in (self.suffix_edit, self.from_edit, self.to_edit,
                       self.delete_checkbox, self.overwrite_checkbox):
            widget.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if running:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def _set_status(self, state, text):
        self.status_chip.setText(text)
        self.status_chip.setProperty('state', state)
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)
        self.status_chip.update()

    # ---------- 文件夹选择 ----------

    def _set_folder(self, path):
        folder = Path(path)
        if not folder.is_dir():
            QMessageBox.warning(self, '无法选择', '该路径不是一个有效文件夹，请重新选择。')
            return
        self.folder = folder
        self.path_edit.setText(str(folder))
        self.path_edit.setCursorPosition(len(str(folder)))
        self.path_edit.setToolTip(str(folder))
        self.drop_zone.set_loaded(True, str(folder))

    def _choose_folder(self):
        start = str(self.folder) if self.folder else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, '选择目标文件夹', start)
        if selected:
            self._set_folder(selected)

    def _clear_folder(self):
        self.folder = None
        self.path_edit.clear()
        self.path_edit.setToolTip('已选择的文件夹完整路径')
        self.drop_zone.set_loaded(False)

    def _require_folder(self):
        if self.folder is None or not self.folder.is_dir():
            QMessageBox.warning(self, '缺少文件夹', '请先拖入或选择一个有效的目标文件夹。')
            return None
        return self.folder

    @staticmethod
    def _normalize_suffix(text):
        suffix = text.strip()
        if not suffix:
            return ''
        if not suffix.startswith('.'):
            suffix = '.' + suffix
        if not SUFFIX_RE.match(suffix):
            return ''
        return suffix

    # ---------- 操作入口 ----------

    def _start_convert(self):
        folder = self._require_folder()
        if not folder:
            return
        suffix = self._normalize_suffix(self.suffix_edit.text())
        if not suffix:
            QMessageBox.warning(self, '后缀无效', '目标后缀只能包含字母、数字、下划线或短横线，例如 urdf。')
            return
        delete_original = self.delete_checkbox.isChecked()
        if delete_original:
            answer = QMessageBox.question(
                self, '确认删除原文件',
                '转换成功后将删除原始文件，此操作不可撤销。\n是否继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        mode = '--auto' if delete_original else '--keep'
        args = [str(folder), suffix, mode]
        self._run(copy_to_plain.main, args,
                  f'转换 · 后缀 {suffix} · ' + ('删除原文件' if delete_original else '保留原文件'))

    def _start_restore_manifest(self):
        folder = self._require_folder()
        if not folder:
            return
        if not (folder / MANIFEST_NAME).is_file():
            QMessageBox.information(
                self, '没有映射清单',
                f'该文件夹下未找到 {MANIFEST_NAME}，无法按清单还原。\n可改用「按后缀还原」。')
            return
        mode = '--force' if self.overwrite_checkbox.isChecked() else '--skip'
        args = [str(folder), mode]
        self._run(restore_from_plain.main, args, '按清单还原 · 读取 ' + MANIFEST_NAME)

    def _start_restore_suffix(self):
        folder = self._require_folder()
        if not folder:
            return
        from_suffix = self._normalize_suffix(self.from_edit.text())
        to_suffix = self._normalize_suffix(self.to_edit.text())
        if not from_suffix or not to_suffix:
            QMessageBox.warning(self, '后缀无效', '还原后缀只能包含字母、数字、下划线或短横线，例如 urdf、hxx。')
            return
        if from_suffix.lower() == to_suffix.lower():
            QMessageBox.warning(self, '后缀重复', '当前后缀与原始后缀不能相同。')
            return
        mode = '--force' if self.overwrite_checkbox.isChecked() else '--skip'
        args = [str(folder), '--from', from_suffix, '--to', to_suffix, mode]
        self._run(restore_from_plain.main, args,
                  f'按后缀还原 · {from_suffix} → {to_suffix}')

    def _run(self, runner, args, description):
        if self._running:
            return
        self._stopped = False
        self._pending_output = ''
        self._stop_event.clear()
        self._set_running(True)
        self._set_status('running', '运行中')
        self.summary_label.setText(description)
        self._append_log('─' * 46, '#475569')
        self._append_log(description, '#93C5FD')

        self.worker = ScriptWorker(runner, args, self._stop_event.is_set, self)
        self.worker.output.connect(self._on_script_output)
        self.worker.done.connect(self._on_script_finished)
        self.worker.start()

    def _stop_process(self):
        if not self._running:
            return
        self._stopped = True
        self._stop_event.set()
        self._set_status('running', '正在停止')
        self._append_log('已发送停止请求，等待当前文件处理完成…', '#FCA5A5')

    def closeEvent(self, event):
        if self._running:
            answer = QMessageBox.question(
                self, '退出', '脚本仍在运行，确定要停止并退出吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_event.set()
            if self.worker and not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait(500)
        event.accept()


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = MainWindow()

    # 按屏幕可用区域收缩窗口，避免在小屏或高缩放比例下超出屏幕
    screen = app.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        window.resize(min(window.width(), available.width() - 48),
                      min(window.height(), available.height() - 48))

    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
