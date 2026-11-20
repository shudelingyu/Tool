"""UI 功能与自适应测试。

说明：Qt 的 offscreen 平台在部分 Windows 环境没有字体数据库，会导致控件尺寸
不可靠，因此这里使用默认的 Windows 平台运行；测试会短暂创建窗口。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from PyQt5.QtCore import QMimeData, QModelIndex, QPoint, QPointF, Qt, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from loglens import parser as parser_module
from loglens.main_window import MainWindow
from loglens.theme import app_stylesheet, ui_family
from loglens.analysis import select_time_context
from loglens.widgets import (
    PER_GROUP_LIMIT,
    ROLE_CONTEXT_ANCHOR,
    ROLE_ENTRY,
    ROLE_GROUP,
    ROLE_GROUP_ENTRIES,
    ROLE_MESSAGE,
    ROLE_NOTICE,
    ROLE_SPANS,
    format_field_value,
    matrix_shape,
)

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "samples" / "demo.log"
DEMO_GBK = ROOT / "samples" / "demo_gbk.log"
PROJECT_STYLE = ROOT / "samples" / "project_style.log"


class UIBase(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        font = QFont(ui_family())
        font.setPixelSize(12)
        cls.app.setFont(font)
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(app_stylesheet())

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1440, 900)
        self.window.show()
        QApplication.processEvents()
        self.load(DEMO)

    def tearDown(self):
        self.window.close()
        QApplication.processEvents()
        self.window.deleteLater()
        QApplication.processEvents()

    def load(self, path: Path, timeout: float = 20.0):
        target = Path(path).resolve()
        self.window.load_file(str(path), confirm_large=False)
        deadline = time.time() + timeout
        while time.time() < deadline:
            QApplication.processEvents()
            result = self.window.result
            if (
                result is not None
                and result.path.resolve() == target
                and not self.window.is_loading
            ):
                QTest.qWait(20)
                return
            QTest.qWait(5)
        self.fail("加载超时")

    def pump(self, ms: int = 40):
        QTest.qWait(ms)
        QApplication.processEvents()


class LoadAndGroupTests(UIBase):
    def test_default_open_directory(self):
        window = MainWindow()
        try:
            self.assertEqual(Path(window._last_dir).resolve(), Path.cwd().resolve())
        finally:
            window.close()
            window.deleteLater()
            QApplication.processEvents()

    def test_load_demo(self):
        result = self.window.result
        self.assertIsNotNone(result)
        self.assertEqual(result.entry_count, 1200)
        self.assertEqual(result.encoding_label, "UTF-8")
        self.assertGreater(self.window.tree.topLevelItemCount(), 0)
        titles = [
            self.window.tree.topLevelItem(i).text(0)
            for i in range(self.window.tree.topLevelItemCount())
        ]
        self.assertEqual(titles, ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.assertEqual(self.window.summary.total_level_counts["ERROR"], 96)
        self.assertEqual(self.window.summary.total_level_counts["CRITICAL"], 20)
        self.assertEqual(self.window.tree.verticalScrollBar().value(), 0)

    def test_source_card_shows_full_file_time_span(self):
        result = self.window.result
        self.assertIsNotNone(result)
        self.assertEqual(result.scan_mode, "full")
        self.assertTrue(result.source_time_range_text)
        label = self.window.sidebar.source._range
        self.assertTrue(label.isVisible())
        self.assertIn("文件时间范围", label.text())
        self.assertIn(
            result.source_time_range_text.replace(" → ", "  →  "), label.text()
        )

    def test_tail_load_shows_full_file_time_span(self):
        total = 400
        base = datetime(2026, 11, 19, 9, 0, 0)
        content = "".join(
            f"{(base + timedelta(seconds=index)):%Y-%m-%d %H:%M:%S} "
            f"INFO core line {index}\n"
            for index in range(total)
        )
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        handle.write(content.encode("utf-8"))
        handle.close()
        try:
            with mock.patch.object(parser_module, "MAX_ENTRIES", 20), mock.patch.object(
                parser_module, "TAIL_SCAN_THRESHOLD", 512
            ), mock.patch.object(parser_module, "READ_BUFFER_BYTES", 1024):
                self.load(Path(handle.name))
            result = self.window.result
            self.assertEqual(result.scan_mode, "tail")
            self.assertEqual(result.entry_count, 20)
            self.assertEqual(result.total_lines, total)
            self.assertEqual(result.first_timestamp, base + timedelta(seconds=380))
            self.assertEqual(result.source_first_timestamp, base)
            self.assertEqual(
                result.source_last_timestamp, base + timedelta(seconds=total - 1)
            )
            expected = result.source_time_range_text.replace(" → ", "  →  ")
            self.assertIn(expected, self.window.sidebar.source._range.text())
            self.assertIn("文件时间范围", self.window._banner_label.text())
            self.assertIn(
                result.source_time_range_text,
                self.window.level_filter._time_chip.toolTip(),
            )
        finally:
            os.unlink(handle.name)

    def test_level_group_counts(self):
        expected = {"TRACE": 15, "DEBUG": 283, "INFO": 647, "WARNING": 139, "ERROR": 96, "CRITICAL": 20}
        for index in range(self.window.tree.topLevelItemCount()):
            item = self.window.tree.topLevelItem(index)
            self.assertTrue(item.data(0, ROLE_GROUP))
            self.assertEqual(len(item.data(0, ROLE_GROUP_ENTRIES)), expected[item.text(0)])
            self.assertGreater(item.childCount(), 0)

    def test_group_header_click_toggles(self):
        tree = self.window.tree
        group = None
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.text(0) == "INFO":
                group = item
                break
        self.assertIsNotNone(group)
        tree.scrollToItem(group)
        self.pump()
        before = group.isExpanded()
        rect = tree.visualItemRect(group)
        self.assertTrue(rect.isValid())
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=rect.center())
        self.pump()
        self.assertNotEqual(before, group.isExpanded())
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=rect.center())
        self.pump()
        self.assertEqual(before, group.isExpanded())

    def test_expand_collapse_all(self):
        self.window.collapse_all()
        self.pump()
        for index in range(self.window.tree.topLevelItemCount()):
            self.assertFalse(self.window.tree.topLevelItem(index).isExpanded())
        self.window.expand_all()
        self.pump(100)
        self.assertTrue(
            any(
                self.window.tree.topLevelItem(i).isExpanded()
                for i in range(self.window.tree.topLevelItemCount())
            )
        )

    def test_select_entry_shows_detail(self):
        tree = self.window.tree
        group = next(
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).text(0) == "ERROR"
        )
        tree.scrollToItem(group)
        if not group.isExpanded():
            group.setExpanded(True)
            self.pump()
        child = group.child(0)
        tree.setCurrentItem(child)
        self.pump()
        entry = self.window.detail_panel.current_entry()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.level, "ERROR")
        self.assertIn("ERROR", entry.raw)

    def test_empty_file_state(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        handle.close()
        try:
            self.load(Path(handle.name))
            self.assertEqual(self.window.result.entry_count, 0)
            self.assertIs(self.window._stack.currentWidget(), self.window._noresult_state)
            self.assertFalse(self.window._export_btn.isEnabled())
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass

    def test_group_rows_span_full_width(self):
        tree = self.window.tree
        group = tree.topLevelItem(0)
        tree.scrollToItem(group)
        self.pump()
        self.assertTrue(tree.isFirstColumnSpanned(0, QModelIndex()))
        self.assertEqual(tree.visualItemRect(group).width(), tree.viewport().width())

    def test_gbk_load(self):
        self.load(DEMO_GBK)
        self.assertEqual(self.window.result.entry_count, 9)
        self.assertIn("GB", self.window.result.encoding_label)
        modules = {entry.module for entry in self.window.matched_entries}
        self.assertIn("安全模块", modules)
        self.assertIn("紧急停止", self.window.tree.topLevelItem(4).child(0).data(0, ROLE_MESSAGE))

    def test_project_style_log_and_field_grouping(self):
        self.load(PROJECT_STYLE)
        self.assertEqual(self.window.result.unstructured_entries, 0)
        table_entries = [
            entry for entry in self.window.matched_entries if "table" in entry.fields
        ]
        self.assertEqual(len(table_entries), 12)
        self.assertTrue(all("joint" in entry.fields for entry in table_entries))
        self.assertTrue(all(entry.module in ("Show::init",) for entry in table_entries))
        self.assertIn("CRITICAL", {entry.level for entry in self.window.matched_entries})
        self.window.set_view_mode("field")
        self.pump()
        self.window._on_field_activated("joint")
        self.pump()
        self.assertEqual(self.window._field_name, "joint")
        titles = {
            self.window.tree.topLevelItem(index).text(0)
            for index in range(self.window.tree.topLevelItemCount())
        }
        self.assertIn("Psm1_joint1", titles)
        self.assertIn("Boom_joint2", titles)


    def test_matrix_field_display(self):
        self.load(PROJECT_STYLE)
        entry = next(e for e in self.window.matched_entries if "tf" in e.fields)
        self.window.detail_panel.set_entry(entry, self.window._query)
        self.pump()
        table = self.window.detail_panel._fields
        item = table.topLevelItem(0)
        text = item.text(0)
        self.assertIn("4×4", text)
        lines = text.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(len(lines[1].split()), 4)
        self.assertEqual(len(lines[4].split()), 4)

    def test_latest_entries_first_and_load_earlier(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "many.log"
            lines = [
                f"2026-11-20 10:{index // 60:02d}:{index % 60:02d}.000 [INFO] module: message {index}"
                for index in range(1005)
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.load(path)
            group = next(
                self.window.tree.topLevelItem(i)
                for i in range(self.window.tree.topLevelItemCount())
                if self.window.tree.topLevelItem(i).text(0) == "INFO"
            )
            if not group.isExpanded():
                group.setExpanded(True)
                self.pump()
            self.assertEqual(group.childCount(), PER_GROUP_LIMIT + 1)
            notice = group.child(0)
            self.assertTrue(notice.data(0, ROLE_NOTICE))
            self.assertIn("最近", notice.data(0, ROLE_NOTICE))
            self.assertEqual(group.child(1).data(0, ROLE_ENTRY).line_no, 6)
            self.assertEqual(group.child(PER_GROUP_LIMIT).data(0, ROLE_ENTRY).line_no, 1005)

            self.window.tree.scrollToItem(notice)
            self.pump()
            rect = self.window.tree.visualItemRect(notice)
            self.assertTrue(rect.isValid())
            QTest.mouseClick(self.window.tree.viewport(), Qt.LeftButton, pos=rect.center())
            self.pump()
            self.assertEqual(group.childCount(), 1005)
            self.assertEqual(group.child(0).data(0, ROLE_ENTRY).line_no, 1)
            self.assertEqual(group.child(1004).data(0, ROLE_ENTRY).line_no, 1005)


class FieldFormatTests(unittest.TestCase):
    def test_matrix_and_vector_formatting(self):
        value = ",".join(str(index) for index in range(16))
        self.assertEqual(matrix_shape("endtf", value), (4, 4))
        rows = format_field_value("endtf", value).splitlines()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].split(), ["0", "1", "2", "3"])
        self.assertEqual(rows[3].split(), ["12", "13", "14", "15"])
        self.assertIsNone(matrix_shape("q", "1,2,3,4"))
        self.assertIsNone(matrix_shape("goal", "0,0,0,0,0,0"))
        self.assertIsNone(matrix_shape("qpos", ",".join(str(i) for i in range(16))))
        self.assertEqual(format_field_value("goal", "0,0,0,0,0,0"), "0, 0, 0, 0, 0, 0")


class FilterTests(UIBase):
    def _error_chip(self):
        return next(
            widget
            for widget in self.window.level_filter._level_widgets
            if widget.property("chipLevel") == "ERROR"
        )

    def test_level_chip_isolates_and_restores(self):
        chip = self._error_chip()
        QTest.mouseClick(chip, Qt.LeftButton)
        self.pump()
        self.assertEqual(len(self.window.matched_entries), 96)
        self.assertEqual({entry.level for entry in self.window.matched_entries}, {"ERROR"})
        QTest.mouseClick(chip, Qt.LeftButton)
        self.pump()
        self.assertEqual(len(self.window.matched_entries), 1200)

    def test_keyword_search_and_highlight(self):
        self.window.set_search_text("overrun", immediate=True)
        self.pump()
        matched = self.window.matched_entries
        self.assertEqual(len(matched), 12)
        self.assertTrue(all("overrun" in entry.message.lower() for entry in matched))
        group = self.window.tree.topLevelItem(0)
        child = group.child(0)
        spans = child.data(0, ROLE_SPANS)
        self.assertTrue(spans)
        self.assertIn("12", self.window._status_matched.text())

    def test_detail_highlight_with_active_search(self):
        self.window.set_search_text("overrun", immediate=True)
        self.pump()
        tree = self.window.tree
        group = next(
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).childCount() > 0
        )
        child = group.child(0)
        tree.setCurrentItem(child)
        self.pump()
        entry = self.window.detail_panel.current_entry()
        self.assertIsNotNone(entry)
        self.assertIn("overrun", entry.raw.lower())
        self.assertTrue(self.window.detail_panel._raw.extraSelections())

    def test_regex_search(self):
        self.window._regex_toggle.setChecked(True)
        self.pump()
        self.window.set_search_text(r"battery=\d+", immediate=True)
        self.pump()
        self.assertGreater(len(self.window.matched_entries), 20)
        for entry in self.window.matched_entries:
            self.assertIn("battery=", entry.raw)
        self.window._regex_toggle.setChecked(False)
        self.pump()

    def test_invalid_regex(self):
        self.window._regex_toggle.setChecked(True)
        self.pump()
        before = len(self.window.matched_entries)
        self.window.set_search_text("(", immediate=True)
        self.pump()
        self.assertTrue(self.window.search.property("invalid"))
        self.assertEqual(len(self.window.matched_entries), before)
        self.window._regex_toggle.setChecked(False)
        self.pump()
        self.assertFalse(self.window.search.property("invalid"))

    def test_module_filter(self):
        self.window._on_module_clicked("planner")
        self.pump()
        self.assertTrue(self.window.matched_entries)
        self.assertTrue(all(entry.module == "planner" for entry in self.window.matched_entries))
        self.assertTrue(self.window.level_filter._module_chip.isVisible())
        self.window._on_module_cleared()
        self.pump()
        self.assertEqual(len(self.window.matched_entries), 1200)

    def test_reset_filters(self):
        self.window._on_module_clicked("planner")
        self.window.set_search_text("failed", immediate=True)
        self.pump()
        self.window.reset_filters()
        self.pump()
        self.assertEqual(len(self.window.matched_entries), 1200)
        self.assertEqual(self.window.search.text(), "")
        self.assertFalse(self.window.level_filter._module_chip.isVisible())

    def test_time_range_filter(self):
        result = self.window.result
        first, last = result.first_timestamp, result.last_timestamp
        midpoint = first + (last - first) / 2
        self.window.apply_time_range(midpoint, last)
        self.pump(400)
        self.assertEqual(self.window._time_start, midpoint)
        self.assertEqual(self.window._time_end, last)
        self.assertIn("时间", self.window.level_filter._time_chip.text())
        matched = self.window.matched_entries
        self.assertGreater(len(matched), 0)
        self.assertLess(len(matched), result.entry_count)
        self.assertTrue(
            all(
                entry.timestamp is not None and entry.timestamp >= midpoint
                for entry in matched
            )
        )
        self.window.reset_filters()
        self.pump(400)
        self.assertIsNone(self.window._time_start)
        self.assertIsNone(self.window._time_end)
        self.assertEqual(self.window.level_filter._time_chip.text(), "时间")
        self.assertEqual(len(self.window.matched_entries), result.entry_count)

    def test_time_range_reloads_truncated_older_entries(self):
        content = "".join(
            f"2026-11-19 09:00:{i:02d} INFO core line {i}\n" for i in range(20)
        )
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        handle.write(content.encode("utf-8"))
        handle.close()
        try:
            with mock.patch.object(parser_module, "MAX_ENTRIES", 5):
                self.load(Path(handle.name))
                self.assertTrue(self.window.result.truncated)
                self.assertEqual(
                    [entry.message for entry in self.window.result.entries],
                    [f"core line {i}" for i in range(15, 20)],
                )

                self.window.apply_time_range(
                    datetime(2026, 11, 19, 9, 0, 2),
                    datetime(2026, 11, 19, 9, 0, 4, 999999),
                )
                deadline = time.time() + 10
                while time.time() < deadline:
                    QApplication.processEvents()
                    if (
                        self.window._range_result is not None
                        and not self.window.is_loading
                    ):
                        break
                    QTest.qWait(10)
                self.assertIsNotNone(self.window._range_result)
                self.assertEqual(
                    [entry.message for entry in self.window.result.entries],
                    [f"core line {i}" for i in range(2, 5)],
                )
                self.assertEqual(
                    [entry.message for entry in self.window.matched_entries],
                    [f"core line {i}" for i in range(2, 5)],
                )
                self.assertIn("当前仅加载", self.window._banner_label.text())

                self.window.apply_time_range(None, None)
                self.pump()
                self.assertEqual(len(self.window.result.entries), 5)
                self.assertEqual(
                    self.window.result.entries[-1].message, "core line 19"
                )
                self.assertEqual(self.window.level_filter._time_chip.text(), "时间")
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass

    def test_double_click_opens_context_dialog(self):
        tree = self.window.tree
        group = next(
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).text(0) == "ERROR"
        )
        if not group.isExpanded():
            group.setExpanded(True)
            self.pump()
        child = next(
            group.child(i)
            for i in range(group.childCount())
            if group.child(i).data(0, ROLE_ENTRY) is not None
        )
        anchor = child.data(0, ROLE_ENTRY)
        self.assertIsNotNone(anchor.timestamp)
        tree.itemDoubleClicked.emit(child, 0)
        self.pump(120)
        dialog = self.window._context_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        expected = select_time_context(
            self.window.result.entries, anchor.timestamp, 30
        )
        count = dialog.tree.topLevelItemCount()
        self.assertEqual(count, len(expected))
        # 平铺展示，没有任何分组行
        self.assertTrue(
            all(
                dialog.tree.topLevelItem(i).data(0, ROLE_ENTRY) is not None
                for i in range(count)
            )
        )
        current = dialog.tree.currentItem()
        self.assertIsNotNone(current)
        self.assertIs(current.data(0, ROLE_ENTRY), anchor)
        self.assertTrue(current.data(0, ROLE_CONTEXT_ANCHOR))
        self.assertEqual(dialog.span_spin.value(), 30)

        # 文本模式：直接展示原始日志文本，并高亮目标日志
        self.assertEqual(dialog.view_stack.currentIndex(), 0)
        dialog.text_button.click()
        self.pump(50)
        self.assertEqual(dialog.view_stack.currentIndex(), 1)
        self.assertIn(anchor.raw, dialog.text_view.toPlainText())
        self.assertEqual(len(dialog.text_view.extraSelections()), 1)
        dialog.text_button.click()
        self.pump(50)
        self.assertEqual(dialog.view_stack.currentIndex(), 0)

        dialog.span_spin.setValue(60)
        self.pump(400)
        expected_wide = select_time_context(
            self.window.result.entries, anchor.timestamp, 60
        )
        self.assertEqual(dialog.tree.topLevelItemCount(), len(expected_wide))

        dialog.copy_button.click()
        self.pump(30)
        clipboard = QApplication.clipboard().text()
        self.assertIn(anchor.raw.splitlines()[0], clipboard)

        dialog.close()
        self.pump(50)

    def test_view_modes(self):
        self.window.set_view_mode("module")
        self.pump()
        self.assertEqual(self.window.tree.topLevelItemCount(), 9)
        self.assertEqual(self.window.tree.verticalScrollBar().value(), 0)
        self.window.set_view_mode("time")
        self.pump()
        self.assertEqual(self.window.tree.topLevelItemCount(), 55)
        self.window.set_view_mode("field")
        self.pump()
        self.assertTrue(self.window._field_bar.isVisible())
        self.assertIsNotNone(self.window._field_name)
        self.assertGreater(self.window.tree.topLevelItemCount(), 1)
        self.assertGreater(self.window._field_combo.count(), 1)
        self.window._on_field_activated("battery")
        self.pump()
        self.assertEqual(self.window._field_name, "battery")
        for index in range(self.window.tree.topLevelItemCount()):
            item = self.window.tree.topLevelItem(index)
            if item.text(0) == "（无该字段）":
                continue
            for entry in item.data(0, ROLE_GROUP_ENTRIES):
                self.assertIn("battery", entry.fields)
        self.window.set_view_mode("level")
        self.pump()
        self.assertEqual(self.window.tree.topLevelItemCount(), 6)
        self.assertFalse(self.window._field_bar.isVisible())


class ImportExportTests(UIBase):
    def test_drag_enter_and_drop(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(DEMO))])
        drag = QDragEnterEvent(
            QPoint(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(self.window, drag)
        QApplication.processEvents()
        self.assertTrue(drag.isAccepted())
        self.assertTrue(self.window._drop_overlay.isVisible())
        drop = QDropEvent(
            QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(self.window, drop)
        self.pump(250)
        deadline = time.time() + 10
        while time.time() < deadline and self.window.is_loading:
            QApplication.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._drop_overlay.isVisible())
        self.assertEqual(self.window.result.path.resolve(), DEMO.resolve())

    def test_export_csv_and_json(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "out.csv"
            json_path = Path(folder) / "out.json"
            count = self.window.export_to(csv_path)
            self.assertEqual(count, 1200)
            self.assertTrue(csv_path.exists())
            with open(csv_path, "r", encoding="utf-8-sig") as handle:
                self.assertEqual(len(handle.readlines()), 1201)
            self.assertEqual(self.window.export_to(json_path), 1200)
            with open(json_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload), 1200)
            self.assertTrue(payload[0]["raw"])
            self.assertIn(payload[0]["level"], {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ResponsiveTests(UIBase):
    def test_columns_adapt(self):
        self.window.resize(1024, 768)
        self.pump(80)
        self.assertEqual(self.window.width(), 1024)
        self.assertTrue(self.window.tree.isColumnHidden(1))
        self.assertTrue(self.window.tree.isColumnHidden(2))
        self.assertTrue(self.window.sidebar.isVisible())
        self.assertTrue(self.window.detail_panel.isVisible())

        self.window.resize(1440, 900)
        self.pump(80)
        self.assertFalse(self.window.tree.isColumnHidden(1))
        self.assertFalse(self.window.tree.isColumnHidden(2))

        self.window.resize(1920, 1080)
        self.pump(80)
        self.assertEqual(self.window.width(), 1920)
        sizes = self.window._splitter.sizes()
        self.assertEqual(len(sizes), 3)
        self.assertGreater(sizes[1], 500)
        self.assertGreater(sizes[2], 250)

    def test_panel_toggles(self):
        self.window._stats_toggle.setChecked(False)
        self.pump()
        self.assertFalse(self.window.sidebar.isVisible())
        self.window._stats_toggle.setChecked(True)
        self.pump()
        self.assertTrue(self.window.sidebar.isVisible())
        self.window._detail_toggle.setChecked(False)
        self.pump()
        self.assertFalse(self.window.detail_panel.isVisible())
        self.window._detail_toggle.setChecked(True)
        self.pump()
        self.assertTrue(self.window.detail_panel.isVisible())

    def test_empty_state_subtitle_not_clipped(self):
        window = MainWindow()
        window.resize(1024, 768)
        window.show()
        self.pump(120)
        subtitle = window._empty_state._subtitle
        required = subtitle.heightForWidth(subtitle.width())
        self.assertGreater(required, 0)
        self.assertGreaterEqual(subtitle.height(), required)
        self.assertGreater(subtitle.height(), subtitle.fontMetrics().lineSpacing())
        window.close()
        window.deleteLater()
        QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
