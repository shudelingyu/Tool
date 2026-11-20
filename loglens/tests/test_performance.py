"""不同规模日志的解析与筛选性能回归测试。"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from loglens.analysis import Query, filter_entries, summarize
from loglens.parser import parse_file

SIZES = (1_000, 25_000, 100_000)


def build_log(path: Path, count: int) -> None:
    levels = ("TRACE", "DEBUG", "INFO", "INFO", "INFO", "WARNING", "ERROR")
    modules = ("mujoco_engine", "motion_control", "planner", "perception", "comms")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for index in range(count):
            level = levels[index % len(levels)]
            module = modules[index % len(modules)]
            handle.write(
                f"2026-11-19 08:{index // 3600 % 60:02d}:{index // 60 % 60:02d}.{index % 1000:03d} "
                f"[{level}] {module}: line {index} value={index % 97} status={'ok' if index % 11 else 'failed'}\n"
            )


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.paths = {}
        for size in SIZES:
            path = Path(cls.folder.name) / f"log_{size}.log"
            build_log(path, size)
            cls.paths[size] = path
        cls.large = parse_file(cls.paths[SIZES[-1]])
        cls.large_seconds = cls.large.duration

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_sizes_are_stable(self):
        for size in SIZES:
            with self.subTest(size=size):
                started = time.perf_counter()
                result = parse_file(self.paths[size])
                elapsed = time.perf_counter() - started
                self.assertEqual(result.entry_count, size)
                self.assertEqual(result.total_lines, size)
                self.assertEqual(result.encoding, "utf-8")
                self.assertLess(elapsed, 30.0, f"{size} 行解析耗时 {elapsed:.2f}s")
                print(f"\n  parse {size:>7,} lines: {elapsed:.3f}s ({size / max(elapsed, 1e-6):,.0f} lines/s)")

    def test_large_filter_performance(self):
        started = time.perf_counter()
        matched = filter_entries(
            self.large.entries,
            Query(text="failed", levels=frozenset({"ERROR"}), case_sensitive=False),
        )
        filter_seconds = time.perf_counter() - started
        started = time.perf_counter()
        summary = summarize(self.large.entries, matched)
        summary_seconds = time.perf_counter() - started
        self.assertGreater(len(matched), 1000)
        self.assertEqual(summary.matched, len(matched))
        self.assertLess(filter_seconds + summary_seconds, 20.0)
        print(
            f"\n  filter {len(self.large.entries):,} lines: {filter_seconds:.3f}s; "
            f"summary: {summary_seconds:.3f}s; matched={len(matched):,}"
        )

    def test_benchmark_note(self):
        print(
            f"\n  benchmark: {SIZES[-1]:,} lines parsed in {self.large_seconds:.3f}s "
            f"({SIZES[-1] / max(self.large_seconds, 1e-6):,.0f} lines/s)"
        )


if __name__ == "__main__":
    unittest.main()
