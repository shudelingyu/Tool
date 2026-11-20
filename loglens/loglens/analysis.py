"""检索、统计聚合、分类分组与结果导出。"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .parser import LEVELS, LogEntry

MAX_LEVEL_GROUPS = len(LEVELS)
MAX_MODULE_GROUPS = 200
MAX_FIELD_STATS = 64
MAX_FIELD_VALUES = 200


class SearchError(ValueError):
    """搜索表达式无效（通常是正则语法错误）。"""


@dataclass(frozen=True)
class Query:
    text: str = ""
    use_regex: bool = False
    case_sensitive: bool = False
    levels: Optional[frozenset[str]] = None
    module: Optional[str] = None
    time_start: Optional[datetime] = None
    time_end: Optional[datetime] = None

    @property
    def has_filters(self) -> bool:
        if self.text.strip() or self.module:
            return True
        if self.time_start is not None or self.time_end is not None:
            return True
        return self.levels is not None and self.levels != frozenset(LEVELS)


def build_pattern(query: Query) -> Optional[re.Pattern[str]]:
    text = query.text.strip()
    if not text:
        return None
    flags = 0 if query.case_sensitive else re.IGNORECASE
    expression = text if query.use_regex else re.escape(text)
    try:
        return re.compile(expression, flags)
    except re.error as exc:
        raise SearchError(str(exc)) from exc


def _entry_matches(entry: LogEntry, pattern: re.Pattern[str]) -> bool:
    if pattern.search(entry.raw):
        return True
    if pattern.search(entry.module):
        return True
    if pattern.search(entry.level):
        return True
    if entry.timestamp_text and pattern.search(entry.timestamp_text):
        return True
    return False


def select_time_context(
    entries: Sequence[LogEntry],
    center: datetime,
    seconds: int,
) -> list[LogEntry]:
    """选取某条日志前后若干秒的记录，并带上紧邻的无时间戳日志。

    无时间戳的日志（如多行响应块）按文件顺序归入相邻时间段：只要它与
    时间范围内的上一条或下一条日志相邻，就一并显示。
    """

    start = center - timedelta(seconds=seconds)
    end = center + timedelta(seconds=seconds)
    selected = [
        entry.timestamp is not None and start <= entry.timestamp <= end
        for entry in entries
    ]
    count = len(entries)
    index = 0
    while index < count:
        if entries[index].timestamp is not None:
            index += 1
            continue
        block_end = index
        while block_end < count and entries[block_end].timestamp is None:
            block_end += 1
        before = index > 0 and selected[index - 1]
        after = block_end < count and selected[block_end]
        if before or after:
            for position in range(index, block_end):
                selected[position] = True
        index = block_end
    context = [entry for entry, keep in zip(entries, selected) if keep]
    if not context:
        return []

    # 时间正序；无时间戳的日志沿用相邻日志的时间参与排序，保持成块相邻
    previous: list[Optional[datetime]] = []
    last_time: Optional[datetime] = None
    for entry in context:
        previous.append(last_time)
        if entry.timestamp is not None:
            last_time = entry.timestamp
    following: list[Optional[datetime]] = [None] * len(context)
    next_time: Optional[datetime] = None
    for position in range(len(context) - 1, -1, -1):
        following[position] = next_time
        if context[position].timestamp is not None:
            next_time = context[position].timestamp

    def sort_key(item: tuple[int, LogEntry]):
        position, entry = item
        if entry.timestamp is not None:
            return entry.timestamp, position
        return previous[position] or following[position] or center, position

    ordered = sorted(enumerate(context), key=sort_key)
    return [entry for _, entry in ordered]


def filter_entries(entries: Sequence[LogEntry], query: Query) -> list[LogEntry]:
    pattern = build_pattern(query)
    levels = query.levels
    if levels is not None:
        levels = frozenset(levels)
        if levels == frozenset(LEVELS):
            levels = None
        elif not levels:
            return []
    module = query.module
    time_start = query.time_start
    time_end = query.time_end
    time_bound = time_start is not None or time_end is not None
    result: list[LogEntry] = []
    for entry in entries:
        if levels is not None and entry.level not in levels:
            continue
        if module is not None and entry.module != module:
            continue
        if time_bound:
            # 有明确时间范围的条目无法判断，统一排除
            if entry.timestamp is None:
                continue
            if time_start is not None and entry.timestamp < time_start:
                continue
            if time_end is not None and entry.timestamp > time_end:
                continue
        if pattern is not None and not _entry_matches(entry, pattern):
            continue
        result.append(entry)
    return result


def find_spans(
    text: str,
    query: Query,
    limit: int = 200,
) -> list[tuple[int, int]]:
    """返回文本中匹配关键词的区间，供表格与详情高亮。"""

    if not text or not query.text.strip():
        return []
    pattern = build_pattern(query)
    if pattern is None:
        return []
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        if start == end:
            continue
        spans.append((start, end))
        if len(spans) >= limit:
            break
    return spans


def level_counts(entries: Iterable[LogEntry]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for entry in entries:
        counter[entry.level] += 1
    return {level: counter.get(level, 0) for level in LEVELS}


def module_counts(entries: Iterable[LogEntry], limit: Optional[int] = None) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for entry in entries:
        counter[entry.module] += 1
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


# ---------------------------------------------------------------------------
# 时间趋势
# ---------------------------------------------------------------------------

_NICE_STEPS = (
    1, 2, 5, 10, 15, 30,
    60, 120, 300, 600, 900, 1800,
    3600, 7200, 10800, 21600, 43200,
    86400, 172800, 604800, 1209600, 2592000,
)


def _nice_step(span_seconds: float) -> int:
    if span_seconds <= 0:
        return 1
    for step in _NICE_STEPS:
        if span_seconds / step <= 100:
            return step
    return _NICE_STEPS[-1]


def _floor_time(value: datetime, step: int) -> datetime:
    base = value.replace(microsecond=0)
    if step % 86400 == 0:
        days = step // 86400
        base = base.replace(hour=0, minute=0, second=0)
        offset = base.toordinal() % days
        return base - timedelta(days=offset)
    if step % 3600 == 0:
        hours = step // 3600
        base = base.replace(minute=0, second=0)
        return base - timedelta(hours=base.hour % hours)
    if step % 60 == 0:
        minutes = step // 60
        base = base.replace(second=0)
        return base - timedelta(minutes=base.minute % minutes)
    timestamp = base.timestamp()
    return datetime.fromtimestamp(timestamp - (timestamp % step))


@dataclass(slots=True)
class TimeHistogram:
    starts: list[datetime]
    step_seconds: int
    counts: list[int]
    missing: int
    first: datetime
    last: datetime

    @property
    def bucket_count(self) -> int:
        return len(self.counts)

    @property
    def peak(self) -> int:
        return max(self.counts) if self.counts else 0

    def bucket_end(self, index: int) -> datetime:
        return self.starts[index] + timedelta(seconds=self.step_seconds)

    def bucket_label(self, index: int) -> str:
        return format_bucket_label(self.starts[index], self.step_seconds)


def format_bucket_label(start: datetime, step: int) -> str:
    end = start + timedelta(seconds=step)
    if step < 60:
        return f"{start:%H:%M:%S} – {end:%H:%M:%S}"
    if step < 86400:
        if start.date() == end.date():
            return f"{start:%H:%M} – {end:%H:%M}"
        return f"{start:%m-%d %H:%M} – {end:%m-%d %H:%M}"
    return f"{start:%Y-%m-%d}"


def build_histogram(entries: Sequence[LogEntry], missing: int = 0) -> Optional[TimeHistogram]:
    timestamps = [entry.timestamp for entry in entries if entry.timestamp is not None]
    if not timestamps:
        return None
    first = min(timestamps)
    last = max(timestamps)
    span = max(0.0, (last - first).total_seconds())
    step = _nice_step(span)
    start = _floor_time(first, step)
    count = int(math.floor((last - start).total_seconds() / step)) + 1
    count = max(1, count)
    counts = [0] * count
    for moment in timestamps:
        index = int((moment - start).total_seconds() // step)
        if index < 0:
            index = 0
        elif index >= count:
            index = count - 1
        counts[index] += 1
    starts = [start + timedelta(seconds=step * index) for index in range(count)]
    return TimeHistogram(
        starts=starts,
        step_seconds=step,
        counts=counts,
        missing=missing,
        first=first,
        last=last,
    )


# ---------------------------------------------------------------------------
# 字段统计与汇总
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FieldStat:
    name: str
    count: int
    values: list[tuple[str, int]]
    overflow: bool = False
    unique: int = 0


def compute_field_stats(entries: Sequence[LogEntry], limit: int = MAX_FIELD_STATS) -> list[FieldStat]:
    name_counter: Counter[str] = Counter()
    values: dict[str, Counter[str]] = {}
    for entry in entries:
        for key, value in entry.fields.items():
            name_counter[key] += 1
            bucket = values.get(key)
            if bucket is None:
                bucket = Counter()
                values[key] = bucket
            if len(bucket) < MAX_FIELD_VALUES or value in bucket:
                bucket[value] += 1

    result: list[FieldStat] = []
    for name, count in name_counter.most_common(limit):
        bucket = values.get(name, Counter())
        result.append(
            FieldStat(
                name=name,
                count=count,
                values=bucket.most_common(3),
                overflow=len(bucket) >= MAX_FIELD_VALUES,
                unique=len(bucket),
            )
        )
    return result


@dataclass(slots=True)
class Summary:
    total: int
    matched: int
    level_counts: dict[str, int]
    total_level_counts: dict[str, int]
    top_modules: list[tuple[str, int]]
    module_total: int
    histogram: Optional[TimeHistogram]
    missing_timestamps: int
    fields: list[FieldStat]

    @property
    def error_count(self) -> int:
        return self.level_counts.get("ERROR", 0) + self.level_counts.get("CRITICAL", 0)

    @property
    def warning_count(self) -> int:
        return self.level_counts.get("WARNING", 0)


def summarize(all_entries: Sequence[LogEntry], matched: Sequence[LogEntry]) -> Summary:
    missing = sum(1 for entry in matched if entry.timestamp is None)
    modules = module_counts(matched)
    return Summary(
        total=len(all_entries),
        matched=len(matched),
        level_counts=level_counts(matched),
        total_level_counts=level_counts(all_entries),
        top_modules=modules[:8],
        module_total=len(modules),
        histogram=build_histogram(matched, missing),
        missing_timestamps=missing,
        fields=compute_field_stats(matched),
    )


# ---------------------------------------------------------------------------
# 分类分组
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LogGroup:
    key: str
    title: str
    entries: list[LogEntry]
    level: Optional[str] = None
    hint: str = ""


def _build_level_groups(entries: Sequence[LogEntry]) -> list[LogGroup]:
    buckets: dict[str, list[LogEntry]] = {level: [] for level in LEVELS}
    for entry in entries:
        buckets.setdefault(entry.level, []).append(entry)
    groups: list[LogGroup] = []
    for level in LEVELS:
        bucket = buckets.get(level) or []
        if bucket:
            groups.append(LogGroup(key=f"level:{level}", title=level, entries=bucket, level=level))
    return groups


def _build_module_groups(entries: Sequence[LogEntry]) -> list[LogGroup]:
    buckets: dict[str, list[LogEntry]] = {}
    for entry in entries:
        buckets.setdefault(entry.module, []).append(entry)
    ordered = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    groups = [
        LogGroup(key=f"module:{name}", title=name, entries=bucket)
        for name, bucket in ordered[:MAX_MODULE_GROUPS]
    ]
    if len(ordered) > MAX_MODULE_GROUPS:
        rest = ordered[MAX_MODULE_GROUPS:]
        merged = [entry for _, bucket in rest for entry in bucket]
        groups.append(
            LogGroup(
                key="module:__other__",
                title="其他模块",
                entries=merged,
                hint=f"{len(rest)} 个模块",
            )
        )
    return groups


def _build_time_groups(
    entries: Sequence[LogEntry],
    histogram: Optional[TimeHistogram],
) -> list[LogGroup]:
    if histogram is None:
        if not entries:
            return []
        return [LogGroup(key="time:__missing__", title="无时间戳", entries=list(entries))]

    buckets: list[list[LogEntry]] = [[] for _ in histogram.starts]
    missing: list[LogEntry] = []
    for entry in entries:
        if entry.timestamp is None:
            missing.append(entry)
            continue
        index = int((entry.timestamp - histogram.starts[0]).total_seconds() // histogram.step_seconds)
        if index < 0:
            index = 0
        elif index >= len(buckets):
            index = len(buckets) - 1
        buckets[index].append(entry)

    groups = [
        LogGroup(
            key=f"time:{histogram.starts[index].isoformat()}",
            title=format_bucket_label(histogram.starts[index], histogram.step_seconds),
            entries=bucket,
        )
        for index, bucket in enumerate(buckets)
        if bucket
    ]
    if missing:
        groups.append(LogGroup(key="time:__missing__", title="无时间戳", entries=missing))
    return groups


def _build_field_groups(entries: Sequence[LogEntry], field: str) -> list[LogGroup]:
    buckets: dict[str, list[LogEntry]] = {}
    missing: list[LogEntry] = []
    for entry in entries:
        value = entry.fields.get(field)
        if value is None or value == "":
            missing.append(entry)
        else:
            buckets.setdefault(value, []).append(entry)
    ordered = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    groups = [
        LogGroup(
            key=f"field:{field}:{value}",
            title=value,
            entries=bucket,
        )
        for value, bucket in ordered[:MAX_MODULE_GROUPS]
    ]
    if len(ordered) > MAX_MODULE_GROUPS:
        rest = ordered[MAX_MODULE_GROUPS:]
        merged = [entry for _, bucket in rest for entry in bucket]
        groups.append(
            LogGroup(
                key=f"field:{field}:__other__",
                title="其他值",
                entries=merged,
                hint=f"{len(rest)} 个值",
            )
        )
    if missing:
        groups.append(
            LogGroup(
                key=f"field:{field}:__missing__",
                title="（无该字段）",
                entries=missing,
                hint=field,
            )
        )
    return groups


def build_groups(
    entries: Sequence[LogEntry],
    mode: str,
    histogram: Optional[TimeHistogram] = None,
    field: Optional[str] = None,
) -> list[LogGroup]:
    if mode == "module":
        return _build_module_groups(entries)
    if mode == "time":
        return _build_time_groups(entries, histogram)
    if mode == "field":
        if not field:
            return []
        return _build_field_groups(entries, field)
    return _build_level_groups(entries)


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


def _entry_record(entry: LogEntry) -> dict:
    return {
        "line": entry.line_no,
        "timestamp": (
            entry.timestamp.isoformat(sep=" ")
            if entry.timestamp is not None
            else entry.timestamp_text
        ),
        "level": entry.level,
        "module": entry.module,
        "message": entry.message,
        "fields": entry.fields,
        "continuation_lines": entry.continuation_lines,
        "raw": entry.raw,
    }


def export_entries(
    entries: Sequence[LogEntry],
    path: str | Path,
    format_name: Optional[str] = None,
) -> int:
    """把日志导出为 CSV / JSON / JSONL / TXT，返回导出条数。"""

    target = Path(path)
    suffix = target.suffix.lower()
    fmt = format_name
    if fmt is None:
        fmt = {
            ".csv": "csv",
            ".json": "json",
            ".jsonl": "jsonl",
            ".ndjson": "jsonl",
            ".txt": "txt",
            ".log": "txt",
        }.get(suffix, "txt")
    fmt = fmt.lower()
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        with open(target, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["行号", "时间", "级别", "模块", "消息", "字段", "原始内容"]
            )
            for entry in entries:
                writer.writerow(
                    [
                        entry.line_no,
                        entry.timestamp.isoformat(sep=" ")
                        if entry.timestamp is not None
                        else entry.timestamp_text,
                        entry.level,
                        entry.module,
                        entry.message,
                        json.dumps(entry.fields, ensure_ascii=False, separators=(",", ":")),
                        entry.raw,
                    ]
                )
        return len(entries)

    if fmt == "jsonl":
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            for entry in entries:
                handle.write(json.dumps(_entry_record(entry), ensure_ascii=False))
                handle.write("\n")
        return len(entries)

    if fmt == "json":
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("[\n")
            for index, entry in enumerate(entries):
                handle.write("  " + json.dumps(_entry_record(entry), ensure_ascii=False))
                handle.write(",\n" if index < len(entries) - 1 else "\n")
            handle.write("]\n")
        return len(entries)

    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(entry.raw)
            handle.write("\n")
    return len(entries)
