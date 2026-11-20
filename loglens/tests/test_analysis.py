"""检索、统计、分组与导出的单元测试。"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from loglens import analysis as analysis_module
from loglens.analysis import (
    Query,
    SearchError,
    build_groups,
    build_histogram,
    export_entries,
    filter_entries,
    find_spans,
    level_counts,
    select_time_context,
    summarize,
)
from loglens.parser import parse_file

LOG_CONTENT = """\
2026-11-19 09:00:00.000 INFO [nav] robot started battery=88
2026-11-19 09:00:01.000 DEBUG [nav] pose update x=1.0 y=2.0
2026-11-19 09:00:02.000 WARNING [lidar] frame dropped count=3
2026-11-19 09:00:03.000 ERROR [planner] no path found reason=collision
2026-11-19 09:00:04.000 CRITICAL [safety] emergency stop engaged
2026-11-19 09:00:05.000 INFO [comms] heartbeat latency_ms=12
2026-11-19 09:00:06.000 INFO [nav] robot started battery=90
plain line without timestamp total failure
"""


def make_entries():
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    try:
        handle.write(LOG_CONTENT.encode("utf-8"))
        handle.close()
        return parse_file(handle.name).entries
    finally:
        os.unlink(handle.name)


class FilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = make_entries()

    def test_plain_search_case_insensitive(self):
        matched = filter_entries(self.entries, Query(text="ROBOT STARTED"))
        self.assertEqual(len(matched), 2)

    def test_case_sensitive(self):
        self.assertEqual(len(filter_entries(self.entries, Query(text="robot started", case_sensitive=True))), 2)
        self.assertEqual(len(filter_entries(self.entries, Query(text="ROBOT", case_sensitive=True))), 0)

    def test_regex_search(self):
        matched = filter_entries(self.entries, Query(text=r"battery=\d+", use_regex=True))
        self.assertEqual(len(matched), 2)

    def test_invalid_regex(self):
        with self.assertRaises(SearchError):
            filter_entries(self.entries, Query(text="(", use_regex=True))

    def test_level_filter(self):
        matched = filter_entries(self.entries, Query(levels=frozenset({"WARNING", "ERROR"})))
        self.assertEqual({entry.level for entry in matched}, {"WARNING", "ERROR"})
        self.assertEqual(len(matched), 3)

    def test_empty_level_set(self):
        self.assertEqual(filter_entries(self.entries, Query(levels=frozenset())), [])

    def test_time_range_filter(self):
        matched = filter_entries(
            self.entries,
            Query(
                time_start=datetime(2026, 11, 19, 9, 0, 3),
                time_end=datetime(2026, 11, 19, 9, 0, 5),
            ),
        )
        self.assertEqual([entry.timestamp.second for entry in matched], [3, 4, 5])

    def test_time_range_excludes_missing_timestamp(self):
        matched = filter_entries(
            self.entries, Query(time_start=datetime(2026, 11, 19, 9, 0, 0))
        )
        self.assertEqual(len(matched), 7)
        self.assertTrue(all(entry.timestamp is not None for entry in matched))

    def test_module_filter(self):
        matched = filter_entries(self.entries, Query(module="nav"))
        self.assertEqual(len(matched), 3)
        self.assertTrue(all(entry.module == "nav" for entry in matched))

    def test_combined_filter(self):
        matched = filter_entries(
            self.entries,
            Query(text="battery", levels=frozenset({"INFO"}), module="nav"),
        )
        self.assertEqual(len(matched), 2)

    def test_find_spans(self):
        spans = find_spans("robot robot", Query(text="robot"))
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0], (0, 5))

    def test_find_spans_regex(self):
        spans = find_spans("x=1 y=22", Query(text=r"\d+", use_regex=True))
        self.assertEqual([text for text in spans], [(2, 3), (6, 8)])


class TimeContextTests(unittest.TestCase):
    CONTENT = """\
2026-11-19 09:00:00.000 INFO [core] t0
line without timestamp before t10
2026-11-19 09:00:10.000 INFO [core] t10
line without timestamp before t20
2026-11-19 09:00:20.000 INFO [core] t20
line without timestamp after t20
2026-11-19 09:10:00.000 INFO [core] t600
line without timestamp between out-of-range
2026-11-19 09:20:00.000 INFO [core] t1200
"""

    @classmethod
    def setUpClass(cls):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        try:
            handle.write(cls.CONTENT.encode("utf-8"))
            handle.close()
            cls.entries = parse_file(handle.name).entries
        finally:
            os.unlink(handle.name)

    def test_context_includes_adjacent_untimestamped_entries(self):
        anchor = next(
            entry for entry in self.entries if entry.message == "t20"
        )
        selected = select_time_context(self.entries, anchor.timestamp, 30)
        messages = [entry.message for entry in selected]
        self.assertEqual(
            messages,
            [
                "t0",
                "line without timestamp before t10",
                "t10",
                "line without timestamp before t20",
                "t20",
                "line without timestamp after t20",
            ],
        )

    def test_context_excludes_unrelated_untimestamped_entries(self):
        anchor = next(
            entry for entry in self.entries if entry.message == "t20"
        )
        selected = select_time_context(self.entries, anchor.timestamp, 30)
        messages = [entry.message for entry in selected]
        self.assertNotIn("t600", messages)
        self.assertNotIn("line without timestamp between out-of-range", messages)
        self.assertNotIn("t1200", messages)

    def test_context_sorted_by_time(self):
        content = (
            "2026-11-19 09:00:20.000 INFO [core] late\n"
            "2026-11-19 09:00:10.000 INFO [core] early\n"
        )
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        try:
            handle.write(content.encode("utf-8"))
            handle.close()
            entries = parse_file(handle.name).entries
        finally:
            os.unlink(handle.name)
        selected = select_time_context(entries, entries[0].timestamp, 30)
        self.assertEqual([entry.message for entry in selected], ["early", "late"])


class StatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = make_entries()
        cls.summary = summarize(cls.entries, cls.entries)

    def test_level_counts(self):
        counts = level_counts(self.entries)
        self.assertEqual(counts["INFO"], 3)
        self.assertEqual(counts["DEBUG"], 1)
        self.assertEqual(counts["WARNING"], 1)
        self.assertEqual(counts["ERROR"], 2)
        self.assertEqual(counts["CRITICAL"], 1)
        self.assertEqual(counts["OTHER"], 0)

    def test_summary(self):
        self.assertEqual(self.summary.total, 8)
        self.assertEqual(self.summary.matched, 8)
        self.assertEqual(self.summary.error_count, 3)
        self.assertEqual(self.summary.warning_count, 1)
        self.assertEqual(self.summary.missing_timestamps, 1)

    def test_histogram(self):
        histogram = build_histogram(self.entries, missing=1)
        self.assertIsNotNone(histogram)
        self.assertEqual(sum(histogram.counts), 7)
        self.assertEqual(histogram.missing, 1)
        self.assertGreaterEqual(histogram.bucket_count, 1)

    def test_histogram_single_timestamp(self):
        subset = [self.entries[0]]
        histogram = build_histogram(subset)
        self.assertEqual(sum(histogram.counts), 1)
        self.assertEqual(histogram.step_seconds, 1)

    def test_field_stats(self):
        names = {stat.name for stat in self.summary.fields}
        self.assertIn("battery", names)
        self.assertIn("count", names)
        self.assertIn("reason", names)


class GroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = make_entries()

    def test_level_groups(self):
        groups = build_groups(self.entries, "level")
        titles = [group.title for group in groups]
        self.assertEqual(titles[0], "DEBUG")
        self.assertEqual(len(groups), 5)
        self.assertEqual(sum(len(group.entries) for group in groups), len(self.entries))

    def test_module_groups(self):
        groups = build_groups(self.entries, "module")
        self.assertEqual(groups[0].title, "nav")
        self.assertEqual(len(groups[0].entries), 3)
        self.assertEqual(sum(len(group.entries) for group in groups), len(self.entries))

    def test_module_group_merge(self):
        with mock.patch.object(analysis_module, "MAX_MODULE_GROUPS", 2):
            groups = build_groups(self.entries, "module")
        self.assertEqual(groups[-1].title, "其他模块")
        self.assertIn("个模块", groups[-1].hint)
        self.assertEqual(sum(len(group.entries) for group in groups), len(self.entries))

    def test_time_groups(self):
        histogram = build_histogram(self.entries, missing=1)
        groups = build_groups(self.entries, "time", histogram)
        self.assertEqual(groups[-1].title, "无时间戳")
        self.assertEqual(sum(len(group.entries) for group in groups), len(self.entries))
        self.assertGreaterEqual(len(groups), 2)

    def test_time_groups_without_timestamps(self):
        subset = [self.entries[-1]]
        groups = build_groups(subset, "time", None)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].title, "无时间戳")

    def test_field_groups(self):
        groups = build_groups(self.entries, "field", None, field="battery")
        titles = [group.title for group in groups]
        self.assertIn("88", titles)
        self.assertIn("90", titles)
        self.assertIn("（无该字段）", titles)
        self.assertEqual(sum(len(group.entries) for group in groups), len(self.entries))

    def test_field_groups_require_field(self):
        self.assertEqual(build_groups(self.entries, "field", None), [])


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = make_entries()

    def _temp_path(self, suffix):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def test_export_csv(self):
        path = self._temp_path(".csv")
        count = export_entries(self.entries, path)
        self.assertEqual(count, len(self.entries))
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), len(self.entries) + 1)
        self.assertEqual(rows[0][0], "行号")
        self.assertEqual(rows[1][2], "INFO")

    def test_export_json(self):
        path = self._temp_path(".json")
        export_entries(self.entries, path)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(len(payload), len(self.entries))
        self.assertEqual(payload[0]["level"], "INFO")
        self.assertIn("battery", payload[0]["fields"])

    def test_export_jsonl(self):
        path = self._temp_path(".jsonl")
        export_entries(self.entries, path)
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        self.assertEqual(len(lines), len(self.entries))
        self.assertEqual(json.loads(lines[0])["module"], "nav")

    def test_export_text(self):
        path = self._temp_path(".txt")
        export_entries(self.entries, path)
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("robot started battery=88", content)
        self.assertEqual(content.count("\n"), len(self.entries))


if __name__ == "__main__":
    unittest.main()
