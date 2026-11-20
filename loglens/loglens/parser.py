"""LogLens 日志解析核心。

职责：
- 通过采样自动识别文本编码（BOM / UTF-8 / UTF-16 / GBK / chardet）；
- 流式解析常见日志格式（log4j、Python logging、Spring Boot、syslog、
  glog、Logcat、JSON Lines 等），提取时间、级别、模块与键值字段；
- 把堆栈、异常等续行归并到上一条日志；
- 通过进度回调与取消回调支撑大文件后台加载。
"""

from __future__ import annotations

import codecs
import io
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

try:  # chardet 是可选的增强依赖，缺失时仍可依靠内置探测
    import chardet  # type: ignore
except Exception:  # pragma: no cover - 极端环境
    chardet = None


LEVELS: tuple[str, ...] = (
    "TRACE",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "OTHER",
)
LEVEL_RANK = {name: index for index, name in enumerate(LEVELS)}

SAMPLE_BYTES = 256 * 1024
MAX_ENTRIES = 300_000
MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GiB，超过后拒绝加载
MAX_LINE_CHARS = 32_768
MAX_ENTRY_CHARS = 131_072
LARGE_FILE_WARN_BYTES = 100 * 1024 * 1024
MAX_FIELDS = 16


class ParseError(RuntimeError):
    """日志解析失败。"""


class BinaryFileError(ParseError):
    """文件看起来是二进制而非文本日志。"""


class EncryptedFileError(ParseError):
    """文件被企业透明加密软件（如 E-SafeNet）加密，当前进程无法读取明文。"""


class ParseCancelled(ParseError):
    """用户取消了加载。"""


def _trace(message: str) -> None:
    path = os.environ.get("LOGLENS_DEBUG_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


@dataclass(slots=True)
class LogEntry:
    """一条结构化日志（可能包含多行堆栈）。"""

    seq: int
    line_no: int
    raw: str
    message: str
    level: str
    timestamp: Optional[datetime]
    timestamp_text: str
    module: str
    fields: dict[str, str] = field(default_factory=dict)
    continuation_lines: int = 0
    truncated: bool = False


@dataclass(slots=True)
class ParseResult:
    """一次文件解析的完整结果。"""

    path: Path
    encoding: str
    file_size: int
    entries: list[LogEntry]
    total_lines: int
    blank_lines: int
    unstructured_entries: int
    duration: float
    truncated: bool = False
    truncation_reason: str = ""
    truncated_entries: int = 0
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    source_first_timestamp: Optional[datetime] = None
    source_last_timestamp: Optional[datetime] = None

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def encoding_label(self) -> str:
        return encoding_label(self.encoding)

    @property
    def time_range_text(self) -> str:
        if self.first_timestamp is None or self.last_timestamp is None:
            return ""
        return (
            f"{self.first_timestamp:%Y-%m-%d %H:%M:%S} → "
            f"{self.last_timestamp:%Y-%m-%d %H:%M:%S}"
        )


# ---------------------------------------------------------------------------
# 编码检测
# ---------------------------------------------------------------------------

_ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 BOM",
    "utf-16": "UTF-16",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "utf-32": "UTF-32",
    "utf-32-le": "UTF-32 LE",
    "utf-32-be": "UTF-32 BE",
    "gb18030": "GB18030",
    "gbk": "GBK",
    "gb2312": "GB2312",
    "big5": "Big5",
    "shift_jis": "Shift-JIS",
    "cp1252": "Windows-1252",
    "latin-1": "Latin-1",
    "ascii": "ASCII",
}


def encoding_label(encoding: str) -> str:
    name = encoding.lower().replace("_", "-")
    return _ENCODING_LABELS.get(name, encoding.upper())


def _normalize_encoding(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    try:
        codec = codecs.lookup(name).name
    except LookupError:
        return None
    codec = codec.lower().replace("_", "-")
    if codec in ("gb2312", "gbk", "euc-cn"):
        return "gb18030"
    if codec in ("ascii", "us-ascii"):
        return "utf-8"
    if codec in ("iso8859-1", "iso-8859-1"):
        return "cp1252"
    return codec


def _can_decode(sample: bytes, encoding: str) -> bool:
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        decoder.decode(sample, final=False)
        return True
    except Exception:
        return False


def _looks_utf16(sample: bytes) -> Optional[str]:
    chunk = sample[:8192]
    if len(chunk) < 8:
        return None
    even_nuls = chunk[0::2].count(0)
    odd_nuls = chunk[1::2].count(0)
    half = len(chunk) // 2
    if half <= 0:
        return None
    if odd_nuls > half * 0.55 and even_nuls < half * 0.05:
        return "utf-16-le"
    if even_nuls > half * 0.55 and odd_nuls < half * 0.05:
        return "utf-16-be"
    return None


def detect_encoding(sample: bytes) -> str:
    """根据文件头采样返回最可能的 Python 编码名。"""

    if not sample:
        return "utf-8"

    # BOM 优先。UTF-32 的 BOM 以 UTF-16 BOM 开头，必须先判断。
    if sample.startswith(codecs.BOM_UTF32_LE) or sample.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith(codecs.BOM_UTF16_LE) or sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"

    utf16 = _looks_utf16(sample)
    if utf16:
        return utf16

    if _can_decode(sample, "utf-8"):
        return "utf-8"

    if chardet is not None:
        try:
            guess = chardet.detect(sample)
            codec = _normalize_encoding(guess.get("encoding"))
            confidence = float(guess.get("confidence") or 0.0)
            if codec and confidence >= 0.45 and _can_decode(sample, codec):
                return codec
        except Exception:
            pass

    # GB18030 覆盖 GBK/GB2312，是中文日志最常见的回退编码。
    for encoding in ("gb18030", "big5", "shift_jis", "cp1252"):
        if _can_decode(sample, encoding):
            return encoding

    return "latin-1"


def _is_binary(sample: bytes, encoding: str) -> bool:
    if not sample:
        return False
    if encoding.startswith(("utf-16", "utf-32")):
        return False
    if sample.count(b"\x00") / len(sample) > 0.08:
        return True
    controls = sum(1 for byte in sample if byte < 9 or 13 < byte < 32)
    return controls / len(sample) > 0.10


# ---------------------------------------------------------------------------
# 时间戳与级别
# ---------------------------------------------------------------------------

_TS_CANDIDATES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "iso",
        re.compile(
            r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
            r"(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?"
        ),
    ),
    (
        "slash",
        re.compile(r"^\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?"),
    ),
    (
        "slash_us",
        re.compile(r"^\d{2}/\d{2}/\d{4}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?"),
    ),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}(?!\d)")),
    (
        "syslog",
        re.compile(r"^[A-Z][a-z]{2}\s{1,2}\d{1,2}\s+\d{2}:\d{2}:\d{2}"),
    ),
    ("epoch_ms", re.compile(r"^\d{13}(?=\s|$)")),
    ("epoch", re.compile(r"^\d{10}(?:\.\d{1,6})?(?=\s|$)")),
    ("time", re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?=\s)")),
)

_MONTHS = {
    name: index
    for index, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}

_LEVEL_WORD = (
    r"TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|CRITICAL|FATAL|"
    r"SEVERE|ALERT|EMERG(?:ENCY)?|VERBOSE"
)
_LEVEL_RE = re.compile(rf"(?i)(?<![\w\-])(?P<level>{_LEVEL_WORD})(?![\w\-])")
_LEVEL_PREFIX_RE = re.compile(rf"^(?P<level>{_LEVEL_WORD})(?![\w\-])", re.I)
_LEVEL_BRACKET_RE = re.compile(
    rf"^[\[\(]\s*(?P<level>{_LEVEL_WORD})\s*[\]\)]\s*[:\-|]?\s*(?P<rest>.*)$",
    re.I,
)

_LEVEL_ALIASES = {
    "TRACE": "TRACE",
    "VERBOSE": "TRACE",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "SEVERE": "ERROR",
    "CRITICAL": "CRITICAL",
    "FATAL": "CRITICAL",
    "PANIC": "CRITICAL",
    "EMERG": "CRITICAL",
    "EMERGENCY": "CRITICAL",
    "ALERT": "CRITICAL",
}

_GLOG_LEVELS = {
    "I": "INFO",
    "W": "WARNING",
    "E": "ERROR",
    "F": "CRITICAL",
    "D": "DEBUG",
    "V": "TRACE",
}

_LOGCAT_LEVELS = {
    "V": "TRACE",
    "D": "DEBUG",
    "I": "INFO",
    "W": "WARNING",
    "E": "ERROR",
    "F": "CRITICAL",
}

_CRITICAL_HINT_RE = re.compile(
    r"(?i)\b(critical|fatal|panic|emergency|segfault|core dumped)\b"
)
_ERROR_HINT_RE = re.compile(
    r"(?i)\b(error|exception|failed|failure|traceback|refused|timeout|timed out)\b"
)
_WARNING_HINT_RE = re.compile(r"(?i)\bwarn(?:ing)?\b")

_GLOG_RE = re.compile(
    r"^(?P<lvl>[IWEFDV])(?P<md>\d{4})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<module>[^\s:]+):(?P<line>\d+)\]\s?(?P<msg>.*)$"
)
_LOGCAT_RE = re.compile(
    r"^(?P<mon>\d{2})-(?P<day>\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d{3,9})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+"
    r"(?P<lvl>[VDIWEF])\s+(?P<module>[^:]+?)\s*:\s?(?P<msg>.*)$"
)
_LOGCAT_SHORT_RE = re.compile(
    r"^(?P<lvl>[VDIWEF])/(?P<module>[^(]+?)\(\s*(?P<pid>\d+)\)\s*:\s?(?P<msg>.*)$"
)
_SPRING_RE = re.compile(
    rf"^(?P<level>{_LEVEL_WORD})\s+\d+\s+---\s+"
    r"\[(?P<thread>[^\]]*)\]\s+(?P<module>\S+)\s*:\s*(?P<msg>.*)$",
    re.I,
)
_PYLOG_LEVEL_FIRST_RE = re.compile(
    rf"^-\s*(?P<level>{_LEVEL_WORD})\s+-\s*"
    r"(?P<module>[^\-]{1,80}?)\s+-\s*(?P<msg>.*)$",
    re.I,
)
_PYLOG_MODULE_FIRST_RE = re.compile(
    rf"^-\s*(?P<module>[^\-]{1,80}?)\s+-\s*"
    r"(?P<level>{_LEVEL_WORD})\s*-\s*(?P<msg>.*)$",
    re.I,
)
_PIPE_RE = re.compile(
    rf"^\|?\s*(?P<level>{_LEVEL_WORD})\s*\|\s*"
    r"(?P<module>[^|]{0,80}?)\s*\|\s*(?P<msg>.*)$",
    re.I,
)

_CONT_MARKER_RE = re.compile(
    r"^(?:Traceback \(most recent call last\):|Caused by:|Suppressed:|"
    r"During handling of the above exception|File \"|at\s+\S|\.\.\.\s*\d+\s+more|"
    r"goroutine\s+\d+|panic:|#\d+\s|"
    r"[A-Z][\w.]*(?:Error|Exception|Throwable)\s*:)"
)

_CONT_BLOCK_RE = re.compile(
    r"^(?:Element name\b|Space Dimension\b|Has kinematics::Solution\b|"
    r"Planning Time\b|Planning error\b|Joint Angles\b|"
    r"\[[^\]]{1,80}\]\s+J\d+\s*=|J\d+\s*=|\.\.\.\s*\(\+\d+ lines\))"
)

_KV_RE = re.compile(
    r"(?<![\w])([A-Za-z_][\w.\-:]{0,40})\s*=\s*"
    r"(?:\"([^\"]{0,240})\"|'([^']{0,240})'|([^\s,;&|{}<>]{1,240}))"
)

_QUICK_TS_RE = re.compile(r"^\[?\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}")
_QUICK_BRACKET_TS_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?\]\s*(?P<rest>.*)$"
)
_BRACKET_TAG_RE = re.compile(r"^\[\s*([^\[\]]{1,240})\s*\](?P<rest>.*)$")
_SOURCE_LOCATION_RE = re.compile(
    r"^(?:[A-Za-z]:)?[^\s\[\]]*[\\/][^\s\[\]]+\.[A-Za-z0-9]{1,8}:\d+$"
)


def _normalize_level(raw: str) -> str:
    key = raw.strip(" []():\t").upper()
    if key.isdigit():
        numeric = int(key)
        if numeric >= 10:  # Python logging: 10/20/30/40/50
            if numeric >= 50:
                return "CRITICAL"
            if numeric >= 40:
                return "ERROR"
            if numeric >= 30:
                return "WARNING"
            if numeric >= 20:
                return "INFO"
            return "DEBUG"
        if numeric == 0:  # syslog severity
            return "CRITICAL"
        if numeric in (1, 2, 3):
            return "ERROR"
        if numeric == 4:
            return "WARNING"
        if numeric == 6:
            return "INFO"
        if numeric == 7:
            return "DEBUG"
        return "OTHER"
    return _LEVEL_ALIASES.get(key, "OTHER")


def _infer_level(text: str) -> str:
    if _CRITICAL_HINT_RE.search(text):
        return "CRITICAL"
    if _ERROR_HINT_RE.search(text):
        return "ERROR"
    if _WARNING_HINT_RE.search(text):
        return "WARNING"
    return "OTHER"


def _clean_module(raw: str) -> str:
    value = raw.strip().strip("[](){}<>\"'`:;, ")
    if not value:
        return "general"
    if len(value) > 64:
        value = value[:61] + "..."
    if _LEVEL_RE.fullmatch(value):
        return "general"
    if re.fullmatch(r"[\d\s.:+\-/]+", value):
        return "general"
    return value


def _clean_message(text: str) -> str:
    value = text.strip()
    value = re.sub(r"^[\s\-–—|>]+\s*", "", value)
    value = re.sub(r"^:[ \t]*", "", value)
    value = value.strip()
    return value or "(空消息)"


def _format_ts(value: datetime) -> str:
    if value.microsecond:
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _localize(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def _parse_timestamp(kind: str, text: str) -> Optional[datetime]:
    now = datetime.now()
    raw = text.strip()
    try:
        if kind == "iso":
            normalized = raw.replace(",", ".")
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
            value = datetime.fromisoformat(normalized)
        elif kind in ("slash", "slash_us"):
            normalized = raw.replace(",", ".").replace("T", " ")
            if kind == "slash":
                fmt = "%Y/%m/%d %H:%M:%S.%f" if "." in normalized else "%Y/%m/%d %H:%M:%S"
            else:
                fmt = "%d/%m/%Y %H:%M:%S.%f" if "." in normalized else "%d/%m/%Y %H:%M:%S"
            value = datetime.strptime(normalized, fmt)
        elif kind == "date":
            value = datetime.strptime(raw, "%Y-%m-%d")
        elif kind == "syslog":
            match = re.match(
                r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
                r"(?P<time>\d{2}:\d{2}:\d{2})$",
                raw,
            )
            if not match:
                return None
            month = _MONTHS.get(match.group("mon"))
            if not month:
                return None
            hour, minute, second = (int(part) for part in match.group("time").split(":"))
            value = datetime(now.year, month, int(match.group("day")), hour, minute, second)
            if value > now + timedelta(days=1):
                value = value.replace(year=value.year - 1)
        elif kind in ("epoch", "epoch_ms"):
            number = float(raw)
            if kind == "epoch_ms" or len(raw.split(".")[0]) >= 13:
                number /= 1000.0
            value = datetime.fromtimestamp(number)
        elif kind == "time":
            normalized = raw.replace(",", ".")
            fmt = "%H:%M:%S.%f" if "." in normalized else "%H:%M:%S"
            parsed = datetime.strptime(normalized, fmt)
            value = now.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=parsed.second,
                microsecond=parsed.microsecond,
            )
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None

    value = _localize(value)
    if not 1970 <= value.year <= 2200:
        return None
    return value


def _match_timestamp(text: str) -> Optional[tuple[datetime, str, str]]:
    for kind, pattern in _TS_CANDIDATES:
        match = pattern.match(text)
        if not match:
            continue
        raw = match.group(0)
        parsed = _parse_timestamp(kind, raw)
        if parsed is None:
            continue
        return parsed, raw, text[match.end():]
    return None


def _extract_timestamp(text: str) -> Optional[tuple[datetime, str, str]]:
    """提取行首时间戳，兼容 ``[2024-...]`` / ``(2024-...)`` 包裹。"""

    stripped = text.lstrip()
    if stripped[:1] in "[(":
        candidate = stripped[1:].lstrip()
        matched = _match_timestamp(candidate)
        if matched:
            parsed, raw, rest = matched
            rest = rest.lstrip()
            if rest[:1] and rest[0] in "])":
                return parsed, raw, rest[1:].lstrip()
            # 例如 [ERROR] ...，不是时间戳包裹
            return None
        return None
    return _match_timestamp(stripped)


def _looks_module_token(token: str) -> bool:
    value = token.strip().strip("[]():,;")
    if not value or len(value) > 80:
        return False
    if _LEVEL_RE.fullmatch(value):
        return False
    if re.fullmatch(r"[\d.+\-/:]+", value):
        return False
    return True


def _module_from_prefix(prefix: str) -> str:
    tokens = [token for token in re.split(r"[\s|]+", prefix) if token]
    for token in reversed(tokens):
        value = token.strip("[]():,;")
        value = re.sub(r"\[\d+\]$", "", value)
        if not value or value in ("-", "|"):
            continue
        if re.fullmatch(r"[\d.+\-/:]+", value):
            continue
        if _looks_module_token(value):
            return _clean_module(value)
    brackets = re.findall(r"\[([^\]]{1,64})\]", prefix)
    if brackets:
        return _clean_module(brackets[-1])
    return "general"


def _is_source_location(text: str) -> bool:
    """判断方括号内容是否为 ``/path/file.cpp:268`` 这类源码位置。"""

    return bool(_SOURCE_LOCATION_RE.match(text.strip()))


def _source_basename(text: str) -> str:
    return re.split(r"[\\/]", text.strip())[-1]


def _split_suffix(suffix: str) -> tuple[str, str, str]:
    """从级别之后的内容中拆出 (module, message, thread)。"""

    suffix = suffix.lstrip(" \t-|:;,>]")
    thread = ""
    match = re.match(r"^\[([^\[\]]{0,240})\]\s*(.*)$", suffix)
    if match:
        inner, remainder = match.group(1), match.group(2)
        if _is_source_location(inner):
            return inner, remainder, ""
        log4j = re.match(r"^([^\s\[\]()]{1,80})\s+-\s+(.*)$", remainder)
        if log4j and _looks_module_token(log4j.group(1)):
            return _clean_module(log4j.group(1)), log4j.group(2), inner
        # 例如 INFO [nav] message，方括号里通常是模块名
        return _clean_module(inner), remainder, ""

    module_dash = re.match(r"^([^\s\[\]()]{1,80}?)\s+-\s+(.*)$", suffix)
    if module_dash and _looks_module_token(module_dash.group(1)):
        return _clean_module(module_dash.group(1)), module_dash.group(2), thread

    module_colon = re.match(r"^([^\s:\[\]()]{1,80})\s*:\s+(.*)$", suffix)
    if module_colon and _looks_module_token(module_colon.group(1)):
        return _clean_module(module_colon.group(1)), module_colon.group(2), thread

    return "", suffix, thread


def _parse_bracket_tag(
    rest: str,
    timestamp: Optional[datetime],
    timestamp_text: str,
) -> Optional[_ParsedLine]:
    """解析 ``[tag] ...`` / ``[tag][info] ...`` 这类方括号标签头。

    LOUT 等项目日志用 ``[codeit]``、``[instrument]`` 作为模块标签，
    级别可能紧跟在后面的第二个方括号中；``[warn][/path/a.cpp:268]``
    这种把源码位置放进方括号的写法也会归一到文件名模块。
    """

    match = _BRACKET_TAG_RE.match(rest)
    if not match:
        return None
    tag = match.group(1).strip()
    # 首方括号是级别时交给 _LEVEL_BRACKET_RE 处理（例如 [INFO] nav: ...）
    if not tag or _LEVEL_RE.fullmatch(tag):
        return None

    remainder = match.group("rest").lstrip()
    fields: dict[str, str] = {}
    source = ""
    if _is_source_location(tag):
        source = tag
        module = _source_basename(tag)
    else:
        module = _clean_module(tag)

    # 标签后还可以再跟一个源码位置方括号，例如 [instrument][/path/a.cpp:12]
    source_match = re.match(r"^\[([^\[\]]{0,240})\]\s*(.*)$", remainder)
    if source_match and _is_source_location(source_match.group(1)):
        source = source_match.group(1)
        remainder = source_match.group(2).lstrip()

    level = "OTHER"
    level_match = _LEVEL_BRACKET_RE.match(remainder)
    if level_match:
        level = _normalize_level(level_match.group("level"))
        remainder = level_match.group("rest") or ""
    else:
        prefix_match = _LEVEL_PREFIX_RE.match(remainder)
        if prefix_match:
            level = _normalize_level(prefix_match.group("level"))
            remainder = remainder[prefix_match.end():]

    message = _clean_message(remainder.lstrip(" \t:-|>,]"))
    if level == "OTHER":
        level = _infer_level(message)
    command_fields = _parse_codeit_command(message)
    if command_fields:
        fields.update(command_fields)
    else:
        fields.update(_extract_fields(message))
    if source:
        fields["source"] = source[:240]

    return _ParsedLine(
        level=level,
        module=module,
        message=message,
        timestamp=timestamp,
        timestamp_text=timestamp_text,
        fields=fields,
        structured=True,
    )


def _extract_fields(message: str, limit: int = 12) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _KV_RE.finditer(message):
        key = match.group(1)
        if key in fields:
            continue
        value = (match.group(2) or match.group(3) or match.group(4) or "").strip()
        if not value or not any(char.isalnum() for char in value):
            continue
        value = value.rstrip(")]};,")
        if not value:
            continue
        fields[key] = value[:240]
        if len(fields) >= limit:
            break
    return fields


_CODEIT_CMD_RE = re.compile(
    r"^server parse cmd\s+(?P<cmd_id>\d+)\s*:\s*\{(?P<body>.*)\}\s*$",
    re.S,
)
_CODEIT_PARAM_RE = re.compile(
    r"--(?P<key>[A-Za-z_][\w.\-]*)"
    r"(?:=(?P<value>\{[^{}]*\}|\[[^\[\]]*\]|\"[^\"]*\"|'[^']*'|[^\s|]+))?"
)
_CODEIT_VALUE_LIMIT = 240


def _normalize_codeit_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and (
        (value[0] == "{" and value[-1] == "}")
        or (value[0] == "[" and value[-1] == "]")
        or (value[0] == value[-1] and value[0] in "\"'")
    ):
        value = value[1:-1].strip()
    value = re.sub(r"\s*,\s*", ",", value)
    return value[:_CODEIT_VALUE_LIMIT]


def _parse_codeit_command(message: str) -> dict[str, str]:
    """解析 codeit 的 ``server parse cmd 8115 : {A||B --k=v||...}``。

    ``||`` 分隔的每一段对应一个 model（索引从 0 开始）：
    第一个词是指令名，``--key=value`` 是该 model 的参数；参数值可能是
    ``{0,0.02,0,0,0,0}`` 这类数组，会被去掉外层括号并规范逗号间距。
    """

    text = message.strip()
    if not text.startswith("server parse cmd"):
        return {}
    match = _CODEIT_CMD_RE.match(text)
    if not match:
        return {}
    segments = match.group("body").split("||")
    fields: dict[str, str] = {
        "cmd_id": match.group("cmd_id"),
        "model_count": str(len(segments)),
    }
    for index, segment in enumerate(segments):
        segment = segment.strip()
        if not segment:
            continue
        if segment.startswith("--"):
            command = ""
            remainder = segment
        else:
            parts = segment.split(None, 1)
            command = parts[0]
            remainder = parts[1] if len(parts) > 1 else ""
        if command:
            fields[f"m{index}.cmd"] = command[:120]
        for param in _CODEIT_PARAM_RE.finditer(remainder):
            key = param.group("key")
            value = param.group("value")
            if value is None:
                value = "1"
            fields[f"m{index}.{key}"] = _normalize_codeit_value(value)
    return fields


_SEQ_NUMBER = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_SEQUENCE_RE = re.compile(
    rf"(?<![\w.'\"])"
    r"(?P<key>[A-Za-z_][\w.:/\-\[\]]{0,40})"
    r"\s*[:=]\s*"
    r"[\[\(\{]?\s*"
    rf"(?P<values>{_SEQ_NUMBER}(?:\s*[,;]\s*{_SEQ_NUMBER})+)"
    r"\s*[\]\)\}]?"
)
_MAX_SEQUENCE_VALUES = 256
_MAX_SEQUENCE_FIELDS = 8
_NUMERIC_LINE_CHARS = set("0123456789+-.,;eE \t[](){}<>")


def _extract_sequence_fields(
    message: str,
    continuation: Optional[list[str]] = None,
    limit: int = _MAX_SEQUENCE_FIELDS,
) -> dict[str, str]:
    """提取 Eigen / std::vector / Span 输出的逗号序列（含跨行矩阵）。

    例：``param:goal=0,0,0,0,0,0``、``q=0.1, 0.2, 0.3``、
    ``tf:`` 后跟多行 ``1.0, 0.0, ...,`` 的 4x4 矩阵。
    """

    if not message:
        return {}
    payload = message
    if continuation:
        payload += " " + " ".join(continuation)
    payload = re.sub(r"\s+", " ", payload)
    result: dict[str, str] = {}
    for match in _SEQUENCE_RE.finditer(payload):
        key = match.group("key").strip(".:")
        if not key:
            continue
        values = [part for part in re.split(r"\s*[,;]\s*", match.group("values")) if part]
        if len(values) < 2:
            continue
        truncated = len(values) > _MAX_SEQUENCE_VALUES
        if truncated:
            values = values[:_MAX_SEQUENCE_VALUES]
        compact = ",".join(values)
        if len(compact) > 512:
            compact = compact[:511] + "…"
        elif truncated:
            compact += "…"
        result[key] = compact
        if len(result) >= limit:
            break
    return result


def _is_numeric_line(text: str) -> bool:
    """判断是否为纯数值序列行（用于 Eigen 多行矩阵等续行）。"""

    stripped = text.strip()
    if not stripped or not any(char.isdigit() for char in stripped):
        return False
    return all(char in _NUMERIC_LINE_CHARS for char in stripped)


@dataclass(slots=True)
class _ParsedLine:
    level: str
    module: str
    message: str
    timestamp: Optional[datetime]
    timestamp_text: str
    fields: dict[str, str]
    structured: bool
    extra_lines: list[str] = field(default_factory=list)


def _parse_json_line(text: str) -> Optional[_ParsedLine]:
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    lowered = {str(key).lower(): key for key in payload}

    def pick(*names: str):
        for name in names:
            key = lowered.get(name.lower())
            if key is not None:
                return payload.get(key), key
        return None, None

    raw_ts, ts_key = pick(
        "@timestamp", "timestamp", "time", "ts", "datetime", "date", "created_at"
    )
    raw_level, level_key = pick("level", "levelname", "severity", "loglevel", "lvl", "priority")
    raw_module, module_key = pick(
        "logger", "module", "source", "service", "name", "component", "tag", "category"
    )
    raw_message, message_key = pick("message", "msg", "text", "event", "log")
    if raw_message is None:
        raw_message, message_key = pick("error", "detail", "description")

    parsed_ts: Optional[datetime] = None
    ts_text = ""
    if isinstance(raw_ts, (int, float)):
        parsed_ts = _parse_timestamp("epoch_ms" if raw_ts > 1e11 else "epoch", str(raw_ts))
        if parsed_ts:
            ts_text = _format_ts(parsed_ts)
    elif isinstance(raw_ts, str):
        found = _match_timestamp(raw_ts)
        if found:
            parsed_ts, ts_text, _ = found
            ts_text = _format_ts(parsed_ts)
        else:
            ts_text = raw_ts[:64]

    level = "OTHER"
    if isinstance(raw_level, str):
        level = _normalize_level(raw_level)
    elif isinstance(raw_level, (int, float)):
        level = _normalize_level(str(int(raw_level)))
    elif raw_level is not None:
        level = _normalize_level(str(raw_level))

    module = _clean_module(str(raw_module)) if raw_module not in (None, "") else "general"

    if isinstance(raw_message, (dict, list)):
        message = json.dumps(raw_message, ensure_ascii=False, separators=(",", ":"))[:4000]
    elif raw_message is None:
        message = "(空消息)"
    else:
        message = str(raw_message)

    if level == "OTHER":
        level = _infer_level(message)

    consumed = {key for key in (ts_key, level_key, module_key, message_key) if key}
    fields: dict[str, str] = {}
    extra_lines: list[str] = []
    for key, value in payload.items():
        if key in consumed:
            continue
        key_text = str(key)
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        if key_text.lower() in (
            "stack_trace", "stacktrace", "traceback", "exception", "exc_info", "stack"
        ) and "\n" in rendered:
            extra_lines.extend(rendered.splitlines()[:80])
            continue
        if len(fields) < MAX_FIELDS:
            fields[key_text] = rendered[:240]

    return _ParsedLine(
        level=level,
        module=module,
        message=message.strip() or "(空消息)",
        timestamp=parsed_ts,
        timestamp_text=ts_text,
        fields=fields,
        structured=True,
        extra_lines=extra_lines,
    )


def _parse_glog(text: str) -> Optional[_ParsedLine]:
    match = _GLOG_RE.match(text)
    if not match:
        return None
    now = datetime.now()
    month = int(match.group("md")[:2])
    day = int(match.group("md")[2:])
    try:
        timestamp = datetime.strptime(
            f"{now.year:04d}-{month:02d}-{day:02d} {match.group('time')}",
            "%Y-%m-%d %H:%M:%S.%f" if "." in match.group("time") else "%Y-%m-%d %H:%M:%S",
        )
    except ValueError:
        timestamp = None
    if timestamp and timestamp > now + timedelta(days=1):
        timestamp = timestamp.replace(year=timestamp.year - 1)
    fields = {"pid": match.group("pid"), "source": f"{match.group('module')}:{match.group('line')}"}
    return _ParsedLine(
        level=_GLOG_LEVELS.get(match.group("lvl"), "OTHER"),
        module=_clean_module(match.group("module")),
        message=_clean_message(match.group("msg")),
        timestamp=timestamp,
        timestamp_text=_format_ts(timestamp) if timestamp else "",
        fields=fields,
        structured=True,
    )


def _parse_logcat(text: str) -> Optional[_ParsedLine]:
    match = _LOGCAT_RE.match(text)
    now = datetime.now()
    if match:
        try:
            timestamp = datetime.strptime(
                f"{now.year:04d}-{match.group('mon')}-{match.group('day')} "
                f"{match.group('time')}",
                "%Y-%m-%d %H:%M:%S.%f",
            )
        except ValueError:
            timestamp = None
        if timestamp and timestamp > now + timedelta(days=1):
            timestamp = timestamp.replace(year=timestamp.year - 1)
        return _ParsedLine(
            level=_LOGCAT_LEVELS.get(match.group("lvl"), "OTHER"),
            module=_clean_module(match.group("module")),
            message=_clean_message(match.group("msg")),
            timestamp=timestamp,
            timestamp_text=_format_ts(timestamp) if timestamp else "",
            fields={"pid": match.group("pid"), "tid": match.group("tid")},
            structured=True,
        )

    short = _LOGCAT_SHORT_RE.match(text)
    if short:
        return _ParsedLine(
            level=_LOGCAT_LEVELS.get(short.group("lvl"), "OTHER"),
            module=_clean_module(short.group("module")),
            message=_clean_message(short.group("msg")),
            timestamp=None,
            timestamp_text="",
            fields={"pid": short.group("pid")},
            structured=True,
        )
    return None


def _parse_rest(
    rest: str,
    timestamp: Optional[datetime],
    timestamp_text: str,
) -> _ParsedLine:
    """解析去掉时间戳后的头部。"""

    rest = rest.lstrip()
    has_ts = timestamp is not None

    if has_ts:
        match = _SPRING_RE.match(rest)
        if match:
            return _ParsedLine(
                level=_normalize_level(match.group("level")),
                module=_clean_module(match.group("module")),
                message=_clean_message(match.group("msg")),
                timestamp=timestamp,
                timestamp_text=timestamp_text,
                fields={"thread": match.group("thread")} if match.group("thread") else {},
                structured=True,
            )

        match = _PYLOG_LEVEL_FIRST_RE.match(rest)
        if match:
            return _ParsedLine(
                level=_normalize_level(match.group("level")),
                module=_clean_module(match.group("module")),
                message=_clean_message(match.group("msg")),
                timestamp=timestamp,
                timestamp_text=timestamp_text,
                fields={},
                structured=True,
            )

        match = _PYLOG_MODULE_FIRST_RE.match(rest)
        if match:
            return _ParsedLine(
                level=_normalize_level(match.group("level")),
                module=_clean_module(match.group("module")),
                message=_clean_message(match.group("msg")),
                timestamp=timestamp,
                timestamp_text=timestamp_text,
                fields={},
                structured=True,
            )

        match = _PIPE_RE.match(rest)
        if match:
            return _ParsedLine(
                level=_normalize_level(match.group("level")),
                module=_clean_module(match.group("module") or "general"),
                message=_clean_message(match.group("msg")),
                timestamp=timestamp,
                timestamp_text=timestamp_text,
                fields={},
                structured=True,
            )

    match = _LEVEL_BRACKET_RE.match(rest)
    if match is None:
        # [codeit] / [instrument][info] 这类标签头优先于正文中的级别关键词
        tagged = _parse_bracket_tag(rest, timestamp, timestamp_text)
        if tagged is not None:
            return tagged
        if has_ts:
            # 时间戳之后的前 160 字符内通常就是日志头，允许级别出现在模块之后
            match = _LEVEL_RE.search(rest[:160])
        else:
            # 没有时间戳时只接受行首级别，避免把正文里的 "info" 当成级别
            match = _LEVEL_PREFIX_RE.match(rest)

    if match:
        level = _normalize_level(match.group("level"))
        if "rest" in match.groupdict():
            suffix = match.group("rest")
            prefix = ""
        else:
            prefix = rest[: match.start()]
            suffix = rest[match.end():]
        module, message, thread = _split_suffix(suffix)
        source = ""
        if module and _is_source_location(module):
            source = module
            module = _source_basename(module)
        if not module:
            module = _module_from_prefix(prefix) if prefix.strip() else "general"
        fields: dict[str, str] = {}
        if thread:
            fields["thread"] = thread
        if source:
            fields["source"] = source[:240]
        fields.update(_extract_fields(message))
        return _ParsedLine(
            level=level,
            module=module,
            message=_clean_message(message),
            timestamp=timestamp,
            timestamp_text=timestamp_text,
            fields=fields,
            structured=True,
        )

    # 时间戳后可能是 syslog 风格 host app[pid]: message
    if has_ts:
        match = re.match(
            r"^(?P<host>[^\s]+)\s+(?P<module>[^\s\[]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<msg>.*)$",
            rest,
        )
        if match and _looks_module_token(match.group("module")):
            fields = {"host": match.group("host")}
            if match.group("pid"):
                fields["pid"] = match.group("pid")
            message = match.group("msg")
            return _ParsedLine(
                level=_infer_level(message),
                module=_clean_module(match.group("module")),
                message=_clean_message(message),
                timestamp=timestamp,
                timestamp_text=timestamp_text,
                fields=fields,
                structured=bool(timestamp),
            )

    match = re.match(r"^\[([^\]]{0,64})\]\s*[:\-|]?\s*(?P<msg>.*)$", rest)
    if match:
        message = match.group("msg")
        return _ParsedLine(
            level=_infer_level(message),
            module=_clean_module(match.group(1)),
            message=_clean_message(message),
            timestamp=timestamp,
            timestamp_text=timestamp_text,
            fields=_extract_fields(message),
            structured=bool(timestamp),
        )

    return _ParsedLine(
        level=_infer_level(rest),
        module="general",
        message=_clean_message(rest),
        timestamp=timestamp,
        timestamp_text=timestamp_text,
        fields=_extract_fields(rest),
        structured=bool(timestamp),
    )


def _parse_line(text: str) -> _ParsedLine:
    stripped = text.strip()
    if stripped.startswith("{"):
        parsed = _parse_json_line(stripped)
        if parsed is not None:
            return parsed

    glog = _parse_glog(stripped)
    if glog is not None:
        return glog
    logcat = _parse_logcat(stripped)
    if logcat is not None:
        return logcat

    extracted = _extract_timestamp(stripped)
    if extracted:
        timestamp, raw_ts, rest = extracted
        return _parse_rest(rest, timestamp, _format_ts(timestamp))

    return _parse_rest(stripped, None, "")


def _looks_like_new_entry(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith("{"):
        return True
    if _GLOG_RE.match(stripped) or _LOGCAT_RE.match(stripped) or _LOGCAT_SHORT_RE.match(stripped):
        return True
    if _extract_timestamp(stripped) is not None:
        return True
    if _LEVEL_BRACKET_RE.match(stripped):
        return True
    return False


def _is_continuation(
    text: str,
    structured_context: bool = False,
    context_level: str = "",
) -> bool:
    stripped = text.lstrip()
    if _QUICK_TS_RE.match(stripped):
        return False
    if _CONT_MARKER_RE.match(stripped):
        return True
    if text[:1].isspace() and not _looks_like_new_entry(stripped):
        return True
    if _looks_like_new_entry(stripped):
        return False
    if structured_context:
        # 错误/警告后的多行详情通常没有时间戳，直接归并
        if context_level in ("ERROR", "CRITICAL", "WARNING"):
            return True
        # 项目日志中的联合角度、OMPL 规划详情等固定多行块
        if _CONT_BLOCK_RE.match(stripped):
            return True
    return False


# ---------------------------------------------------------------------------
# ASCII 表格日志（项目 main.log 中的 Show / 参数表）
# ---------------------------------------------------------------------------


def _is_table_border(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 5 or not stripped.startswith("+") or not stripped.endswith("+"):
        return False
    return all(char in "+-= " for char in stripped) and ("-" in stripped or "=" in stripped)


def _split_table_row(text: str) -> Optional[list[str]]:
    stripped = text.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    if stripped.count("|") < 2:
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _normalize_table_headers(cells: list[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, cell in enumerate(cells):
        key = cell.strip()
        if key == "#":
            key = "index"
        if not key:
            key = f"col{index + 1}"
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 1
        headers.append(key)
    return headers


def _is_table_header(cells: list[str]) -> bool:
    if not cells:
        return False
    first = cells[0].strip().lower()
    lowered = [cell.strip().lower() for cell in cells]
    return first in ("#", "index") or ("joint" in lowered and not first.isdigit())


def _table_type(headers: list[str]) -> str:
    lowered = [header.lower() for header in headers]
    if any(header.startswith("fb.") for header in lowered):
        return "joint_feedback"
    if "lower[rad]" in lowered or "upper[rad]" in lowered:
        return "joint_limits"
    if any("upper" in header or "lower" in header for header in lowered):
        return "joint_limits"
    if "joint" in lowered:
        return "joint_table"
    return "table"


@dataclass(slots=True)
class _Context:
    timestamp: Optional[datetime]
    timestamp_text: str
    level: str
    module: str


# ---------------------------------------------------------------------------
# 文件解析
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PendingEntry:
    line_no: int
    parsed: _ParsedLine
    lines: list[str]
    chars: int
    omitted: int = 0
    truncated: bool = False

    def append(self, line: str) -> None:
        if self.chars >= MAX_ENTRY_CHARS:
            self.omitted += 1
            return
        remaining = MAX_ENTRY_CHARS - self.chars
        if len(line) > remaining:
            self.lines.append(line[:remaining] + " …")
            self.chars = MAX_ENTRY_CHARS
            self.truncated = True
            self.omitted += 1
            self._merge_fields(line)
            return
        self.lines.append(line)
        self.chars += len(line) + 1
        self._merge_fields(line)

    def _merge_fields(self, line: str) -> None:
        if len(self.parsed.fields) >= MAX_FIELDS:
            return
        for key, value in _extract_fields(line).items():
            if len(self.parsed.fields) >= MAX_FIELDS:
                break
            self.parsed.fields.setdefault(key, value)


def _finalize_entry(pending: _PendingEntry, seq: int) -> LogEntry:
    raw = "\n".join(pending.lines)
    if pending.omitted:
        raw += f"\n… [已省略 {pending.omitted} 行]"
    fields = dict(pending.parsed.fields)
    continuation = pending.lines[1:]
    has_sequence_hint = "," in pending.parsed.message or ";" in pending.parsed.message
    if not has_sequence_hint and continuation:
        has_sequence_hint = any(
            "," in line or ";" in line for line in continuation
        )
    # codeit 指令已按 model 拆出参数，避免再生成含义重复的全局序列字段
    if has_sequence_hint and "cmd_id" not in fields:
        fields.update(_extract_sequence_fields(pending.parsed.message, continuation))
    return LogEntry(
        seq=seq,
        line_no=pending.line_no,
        raw=raw,
        message=pending.parsed.message,
        level=pending.parsed.level,
        timestamp=pending.parsed.timestamp,
        timestamp_text=pending.parsed.timestamp_text,
        module=pending.parsed.module,
        fields=fields,
        continuation_lines=len(pending.lines) - 1,
        truncated=pending.truncated,
    )


def parse_file(
    path: str | os.PathLike[str],
    *,
    progress: Optional[Callable[[int, int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    time_start: Optional[datetime] = None,
    time_end: Optional[datetime] = None,
) -> ParseResult:
    """流式解析日志文件。

    ``progress`` 参数：``(已读字节, 文件总字节, 已解析条目数)``。
    ``should_cancel`` 返回 True 时抛出 :class:`ParseCancelled`。
    指定 ``time_start`` / ``time_end`` 时只保留该时间范围内的日志，
    用于超过 300,000 条、较早记录已被截断时按时间段重新读取。
    """

    file_path = Path(path)
    started = time.perf_counter()
    try:
        stat = file_path.stat()
    except OSError as exc:
        raise ParseError(f"无法访问文件：{exc}") from exc
    if not file_path.is_file():
        raise ParseError("目标不是文件")
    if stat.st_size > MAX_FILE_BYTES:
        raise ParseError(
            f"文件大小 {stat.st_size / 1024 / 1024:.1f} MB 超过 1 GB 上限"
        )

    try:
        with open(file_path, "rb") as probe:
            sample = probe.read(SAMPLE_BYTES)
    except OSError as exc:
        raise ParseError(f"读取文件失败：{exc}") from exc

    if not sample:
        return ParseResult(
            path=file_path,
            encoding="utf-8",
            file_size=stat.st_size,
            entries=[],
            total_lines=0,
            blank_lines=0,
            unstructured_entries=0,
            duration=time.perf_counter() - started,
        )

    header_sample = sample[:16384]
    if b"E-SafeNet" in header_sample or b"E-SAFENET" in header_sample:
        raise EncryptedFileError(
            f"文件 {file_path.name} 似乎被 E-SafeNet 透明加密。\n\n"
            "当前程序运行在加密软件白名单之外，只能读到密文。请任选一种方式：\n"
            "1. 将 LogLens.exe 加入 E-SafeNet / 企业加密软件的白名单；\n"
            "2. 双击 run_loglens.pyw（使用受信任的 Python 运行），或运行\n"
            "   pythonw.exe run_loglens.pyw \"日志路径\"；\n"
            "3. 将日志解密或导出为普通文本后再导入。"
        )

    encoding = detect_encoding(sample)
    _trace(
        f"parse {file_path} size={stat.st_size} sample={len(sample)} "
        f"head={sample[:32].hex()} encoding={encoding} "
        f"utf8={_can_decode(sample, 'utf-8')} binary={_is_binary(sample, encoding)}"
    )
    if _is_binary(sample, encoding):
        raise BinaryFileError(
            f"文件 {file_path.name} 包含大量二进制字节（检测编码：{encoding_label(encoding)}），"
            "可能不是文本日志。"
        )

    # 超过上限时丢弃最早记录，始终保留最近的 MAX_ENTRIES 条
    entries: deque[LogEntry] = deque(maxlen=MAX_ENTRIES)
    produced = 0
    kept_total = 0
    pending: Optional[_PendingEntry] = None
    last_context: Optional[_Context] = None
    table_headers: list[str] = []
    total_lines = 0
    blank_lines = 0
    unstructured = 0
    truncated = False
    truncation_reason = ""
    truncated_entries = 0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    source_first_ts: Optional[datetime] = None
    source_last_ts: Optional[datetime] = None
    time_filter_active = time_start is not None or time_end is not None

    def track_source(entry: LogEntry) -> None:
        nonlocal source_first_ts, source_last_ts
        moment = entry.timestamp
        if moment is None:
            return
        if source_first_ts is None or moment < source_first_ts:
            source_first_ts = moment
        if source_last_ts is None or moment > source_last_ts:
            source_last_ts = moment

    def keep_entry(entry: LogEntry) -> bool:
        if not time_filter_active:
            return True
        moment = entry.timestamp
        if moment is None:
            return False
        if time_start is not None and moment < time_start:
            return False
        if time_end is not None and moment > time_end:
            return False
        return True

    def flush() -> None:
        nonlocal pending, unstructured, truncated_entries, last_context, produced, kept_total
        if pending is None:
            return
        # LOUT 等日志会在同一批输出中省略后续行的时间戳，沿用上一条结构化日志的时间
        if (
            pending.parsed.timestamp is None
            and pending.parsed.structured
            and last_context is not None
            and last_context.timestamp is not None
        ):
            pending.parsed.timestamp = last_context.timestamp
            pending.parsed.timestamp_text = last_context.timestamp_text
        structured = pending.parsed.structured
        entry = _finalize_entry(pending, produced)
        produced += 1
        track_source(entry)
        if structured:
            last_context = _Context(
                timestamp=entry.timestamp,
                timestamp_text=entry.timestamp_text,
                level=entry.level,
                module=entry.module,
            )
        if keep_entry(entry):
            entries.append(entry)
            if not structured:
                unstructured += 1
            if entry.truncated:
                truncated_entries += 1
            kept_total += 1
        pending = None

    def append_table_row(cells: list[str], line_no: int, raw: str) -> None:
        nonlocal produced, kept_total
        headers_local = table_headers or [
            f"col{index + 1}" for index in range(len(cells))
        ]
        fields: dict[str, str] = {}
        for key, value in zip(headers_local, cells):
            if value:
                fields[key] = value[:240]
        fields["table"] = _table_type(headers_local)

        context = last_context
        timestamp = context.timestamp if context is not None else None
        timestamp_text = context.timestamp_text if context is not None else ""
        level = "INFO"
        module = "table"
        if context is not None:
            level = context.level if context.level != "OTHER" else "INFO"
            module = context.module or "table"

        message = " | ".join(cell for cell in cells if cell) or "(空表格行)"
        entry = LogEntry(
            seq=produced,
            line_no=line_no,
            raw=raw,
            message=message,
            level=level,
            timestamp=timestamp,
            timestamp_text=timestamp_text,
            module=module,
            fields=fields,
        )
        produced += 1
        track_source(entry)
        if keep_entry(entry):
            entries.append(entry)
            kept_total += 1

    last_progress = 0.0
    try:
        with open(file_path, "rb") as binary:
            with io.TextIOWrapper(
                binary, encoding=encoding, errors="replace", newline=None
            ) as reader:
                for line_no, line in enumerate(reader, start=1):
                    total_lines = line_no
                    if line_no % 2048 == 0:
                        if should_cancel is not None and should_cancel():
                            raise ParseCancelled("已取消加载")
                        if progress is not None:
                            now = time.perf_counter()
                            if now - last_progress >= 0.08:
                                last_progress = now
                                progress(
                                    min(binary.tell(), stat.st_size),
                                    stat.st_size,
                                    len(entries),
                                )

                    text = line.rstrip("\r\n")
                    if not text.strip():
                        blank_lines += 1
                        continue

                    if _is_table_border(text):
                        if pending is not None:
                            flush()
                        continue

                    cells = _split_table_row(text)
                    if cells is not None:
                        if pending is not None:
                            flush()
                        if _is_table_header(cells):
                            table_headers = _normalize_table_headers(cells)
                            continue
                        append_table_row(cells, line_no, text)
                        continue

                    # LOUT 等日志：标题行（以 : 结尾）后跟带时间戳的纯数值行
                    if pending is not None and pending.parsed.structured:
                        quick = _QUICK_BRACKET_TS_RE.match(text)
                        if quick is not None:
                            quick_rest = quick.group("rest").strip()
                            if not quick_rest or _is_numeric_line(quick_rest):
                                last_line = (
                                    pending.lines[-1].strip() if pending.lines else ""
                                )
                                if (
                                    last_line.endswith((":", "="))
                                    or pending.parsed.message.rstrip().endswith((":", "="))
                                ):
                                    pending.append(text)
                                    continue

                    if pending is not None and _is_continuation(
                        text, pending.parsed.structured, pending.parsed.level
                    ):
                        pending.append(text)
                        continue

                    # 只有时间戳的标题行：后续无时间戳内容归并为它的正文
                    if (
                        pending is not None
                        and pending.parsed.structured
                        and pending.parsed.message == "(空消息)"
                        and not _looks_like_new_entry(text)
                    ):
                        pending.parsed.message = _clean_message(text)
                        pending.append(text)
                        continue

                    # Eigen 多行矩阵 / 向量：键行以 : 或 = 结尾，随后是纯数值行
                    if (
                        pending is not None
                        and pending.parsed.structured
                        and _is_numeric_line(text)
                    ):
                        last_line = pending.lines[-1].strip() if pending.lines else ""
                        opens_sequence = (
                            last_line.endswith((":", "="))
                            or _is_numeric_line(last_line)
                            or pending.parsed.message.rstrip().endswith((",", ":", "="))
                        )
                        if opens_sequence:
                            pending.append(text)
                            continue

                    flush()

                    if len(text) > MAX_LINE_CHARS:
                        text = text[:MAX_LINE_CHARS] + " …"
                    parsed = _parse_line(text)
                    table_headers = []
                    pending = _PendingEntry(
                        line_no=line_no,
                        parsed=parsed,
                        lines=[text],
                        chars=len(text) + 1,
                    )
                    for extra in parsed.extra_lines:
                        pending.append(extra)

                flush()
    except ParseCancelled:
        raise
    except OSError as exc:
        raise ParseError(f"读取文件失败：{exc}") from exc

    if progress is not None:
        progress(stat.st_size, stat.st_size, len(entries))

    dropped_entries = max(0, kept_total - len(entries))
    truncated = dropped_entries > 0
    if truncated:
        if time_filter_active:
            truncation_reason = (
                f"所选时间范围内日志条目超过 {MAX_ENTRIES:,} 条上限，"
                f"仅保留最近 {MAX_ENTRIES:,} 条"
                f"（范围内共 {kept_total:,} 条，已忽略最早 {dropped_entries:,} 条）"
            )
        else:
            truncation_reason = (
                f"日志条目超过 {MAX_ENTRIES:,} 条上限，仅保留最近 {MAX_ENTRIES:,} 条"
                f"（已忽略最早 {dropped_entries:,} 条）"
            )

    timestamps = [entry.timestamp for entry in entries if entry.timestamp is not None]
    if timestamps:
        first_ts = min(timestamps)
        last_ts = max(timestamps)
    else:
        first_ts = None
        last_ts = None

    return ParseResult(
        path=file_path,
        encoding=encoding,
        file_size=stat.st_size,
        entries=list(entries),
        total_lines=total_lines,
        blank_lines=blank_lines,
        unstructured_entries=unstructured,
        duration=time.perf_counter() - started,
        truncated=truncated,
        truncation_reason=truncation_reason,
        truncated_entries=truncated_entries,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        source_first_timestamp=source_first_ts,
        source_last_timestamp=source_last_ts,
    )
