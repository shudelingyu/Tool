"""日志解析核心的单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from loglens import parser as parser_module
from loglens.parser import (
    BinaryFileError,
    EncryptedFileError,
    ParseCancelled,
    detect_encoding,
    parse_file,
)


def parse_bytes(data: bytes, suffix: str = ".log"):
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(data)
        handle.close()
        return parse_file(handle.name)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


class EncodingDetectionTests(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(detect_encoding("时间 INFO 启动".encode("utf-8")), "utf-8")

    def test_utf8_bom(self):
        self.assertEqual(detect_encoding(b"\xef\xbb\xbfINFO hello"), "utf-8-sig")

    def test_gbk(self):
        sample = ("2026-11-19 09:00:00 INFO 导航模块启动成功\n" * 40).encode("gbk")
        encoding = detect_encoding(sample)
        self.assertIn(encoding, ("gb18030", "gbk", "gb2312"))
        actual = encoding if encoding != "gbk" else "gb18030"
        sample.decode(actual)

    def test_utf16(self):
        sample = "2026-11-19 09:00:00 INFO 导航模块\n".encode("utf-16")
        self.assertEqual(detect_encoding(sample), "utf-16")

    def test_utf16_without_bom(self):
        sample = ("INFO line with ascii text\n" * 20).encode("utf-16-le")
        self.assertEqual(detect_encoding(sample), "utf-16-le")

    def test_latin1(self):
        sample = ("2026-11-19 09:00:00 INFO caf\u00e9 service\n" * 20).encode("latin-1")
        encoding = detect_encoding(sample)
        self.assertIn(encoding, ("cp1252", "latin-1"))
        sample.decode(encoding)


class ParsingFormatTests(unittest.TestCase):
    def test_bracket_format(self):
        result = parse_bytes(
            b"2026-11-19 09:14:03.128 [INFO] nav_controller: robot pose updated x=1.24 y=0.58\n"
        )
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "nav_controller")
        self.assertIn("robot pose", entry.message)
        self.assertEqual(entry.fields.get("x"), "1.24")
        self.assertEqual(entry.timestamp.year, 2026)

    def test_python_logging_format(self):
        result = parse_bytes(
            b"2026-11-19 09:14:04,200 - perception - WARNING - lidar frame dropped count=3\n"
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.module, "perception")
        self.assertEqual(entry.fields.get("count"), "3")

    def test_level_before_module(self):
        result = parse_bytes(
            b'2026-11-19 09:14:05.301 ERROR [planner] trajectory failed reason="collision"\n'
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.module, "planner")
        self.assertEqual(entry.fields.get("reason"), "collision")

    def test_iso_z_format(self):
        result = parse_bytes(b"2026-11-19T09:14:06.400Z INFO comms - heartbeat ok\n")
        entry = result.entries[0]
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "comms")
        self.assertEqual(entry.message, "heartbeat ok")

    def test_time_only_and_bracket_module(self):
        result = parse_bytes(b"09:14:07 [DEBUG] [control] pid loop dt=0.001\n")
        entry = result.entries[0]
        self.assertEqual(entry.level, "DEBUG")
        self.assertEqual(entry.module, "control")
        self.assertEqual(entry.fields.get("dt"), "0.001")

    def test_bracket_level_without_timestamp(self):
        result = parse_bytes(b"[ERROR] [safety] emergency stop engaged\n")
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.module, "safety")
        self.assertIsNone(entry.timestamp)

    def test_spring_boot_format(self):
        result = parse_bytes(
            b"2026-11-19 09:14:03.123  INFO 1234 --- [main] c.f.NavService : started\n"
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "c.f.NavService")
        self.assertEqual(entry.fields.get("thread"), "main")

    def test_glog_format(self):
        result = parse_bytes(b"I1119 09:14:03.123456  1234 nav.cc:88] pose updated\n")
        entry = result.entries[0]
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "nav.cc")
        self.assertEqual(entry.fields.get("pid"), "1234")
        self.assertEqual(entry.timestamp.month, 11)

    def test_logcat_format(self):
        result = parse_bytes(
            b"11-19 09:14:03.123  1234  5678 E ActivityManager: crash detected\n"
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.module, "ActivityManager")
        self.assertEqual(entry.fields.get("tid"), "5678")

    def test_nginx_error_format(self):
        result = parse_bytes(
            b"2026/11/19 09:14:03 [error] 123#0: *1 open() failed\n"
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.timestamp.year, 2026)

    def test_syslog_format(self):
        result = parse_bytes(b"Nov 19 09:14:03 host app[123]: service started\n")
        entry = result.entries[0]
        self.assertEqual(entry.module, "app")
        self.assertEqual(entry.fields.get("host"), "host")
        self.assertEqual(entry.fields.get("pid"), "123")

    def test_plain_text_heuristic(self):
        result = parse_bytes("something went wrong: connection failed\n".encode("utf-8"))
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.module, "general")
        self.assertIsNone(entry.timestamp)
        self.assertEqual(result.unstructured_entries, 1)

    def test_json_lines(self):
        result = parse_bytes(
            b'{"timestamp":"2026-11-19T10:00:00.123Z","level":"warn",'
            b'"logger":"gateway","message":"slow request","latency_ms":345,'
            b'"request_id":"abc"}\n'
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.module, "gateway")
        self.assertEqual(entry.message, "slow request")
        self.assertEqual(entry.fields.get("latency_ms"), "345")
        self.assertIsNotNone(entry.timestamp)

    def test_json_numeric_level_and_epoch(self):
        result = parse_bytes(
            b'{"time":1763500000,"level":40,"module":"db","msg":"connection lost"}\n'
        )
        entry = result.entries[0]
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.module, "db")
        self.assertIsNotNone(entry.timestamp)

    def test_stack_trace_continuation(self):
        content = (
            "2026-11-19 09:14:05.301 ERROR [planner] trajectory failed\n"
            "Traceback (most recent call last):\n"
            '  File "planner.py", line 42, in plan\n'
            "    raise RuntimeError(\"no path\")\n"
            "RuntimeError: no path\n"
            "2026-11-19 09:14:06.000 INFO [planner] recovered\n"
        )
        result = parse_bytes(content.encode("utf-8"))
        self.assertEqual(len(result.entries), 2)
        error = result.entries[0]
        self.assertEqual(error.level, "ERROR")
        self.assertEqual(error.continuation_lines, 4)
        self.assertIn("RuntimeError: no path", error.raw)
        self.assertEqual(result.entries[1].level, "INFO")

    def test_blank_and_malformed_lines(self):
        result = parse_bytes(b"\n\n  \n2026-11-19 09:00:00 INFO ok\n\xff\xfe broken\n")
        self.assertEqual(result.blank_lines, 3)
        self.assertGreaterEqual(len(result.entries), 2)

    def test_chinese_gbk_roundtrip(self):
        content = "2026-11-19 09:00:00 INFO 导航模块: 机器人启动成功\n"
        result = parse_bytes(content.encode("gbk"))
        entry = result.entries[0]
        self.assertEqual(entry.module, "导航模块")
        self.assertIn("机器人启动成功", entry.message)

    def test_utf16_file(self):
        content = "2026-11-19 09:00:00 WARNING core: 电量偏低 battery=18\n"
        result = parse_bytes(content.encode("utf-16"))
        entry = result.entries[0]
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.fields.get("battery"), "18")


class ProjectLogTests(unittest.TestCase):
    """适配项目 main.log 的 [时间][级别] + ASCII 表格格式。"""

    CONTENT = """\
[2026-11-19 09:00:00.000][info] =================================LOG START===================================
[2026-11-19 09:00:00.030][info] [Show::init] robot 'Psm1'  id=1  dof=8 motion=PID
+---+-------------+----------+-------+------------+------------+
| # | joint       | mode     | ladrc | lower[rad] | upper[rad] |
+---+-------------+----------+-------+------------+------------+
| 0 | Psm1_joint0 | POSITION | off   |   -1.36136 |    0.78540 |
| 1 | Psm1_joint1 | POSITION | off   |   -0.05000 |    0.35000 |
+---+-------------+----------+-------+------------+------------+
[2026-11-19 09:00:00.035][info] [Show::init] fb  q=   0.08800  joint_num=8)
[2026-11-19 09:00:01.000][error] [Controller::load_xml] Load model error: bad STL
Element name 'link4', id 4, line 39
[2026-11-19 09:00:02.000][info] [CommandScheduler::init_loop] param:angle=30.0 param:axis=z
[2026-11-19 09:00:03.000][info] [MuJoCoViewer::drawJointAngles] [dbg] lines=9
Joint Angles (deg; mm if sliding):
[YC200_Psm1] J0=    0.00  J1=   100.0mm  J2=  -100.0mm
  J4=    0.01  J5=    0.02
... (+2 lines)
[2026-11-19 09:00:04.000][info] [saveWindowState] window_config saved
"""

    @classmethod
    def setUpClass(cls):
        cls.result = parse_bytes(cls.CONTENT.encode("utf-8"))

    def test_lowercase_levels_and_modules(self):
        levels = [entry.level for entry in self.result.entries]
        self.assertIn("INFO", levels)
        self.assertIn("ERROR", levels)
        self.assertNotIn("OTHER", levels)
        self.assertEqual(self.result.unstructured_entries, 0)
        show = next(entry for entry in self.result.entries if entry.module == "Show::init")
        self.assertEqual(show.level, "INFO")

    def test_ascii_table_rows_become_entries(self):
        tables = [entry for entry in self.result.entries if "table" in entry.fields]
        self.assertEqual(len(tables), 2)
        first = tables[0]
        self.assertEqual(first.fields["joint"], "Psm1_joint0")
        self.assertEqual(first.fields["mode"], "POSITION")
        self.assertEqual(first.fields["table"], "joint_limits")
        self.assertEqual(first.level, "INFO")
        self.assertEqual(first.module, "Show::init")
        self.assertIsNotNone(first.timestamp)
        self.assertEqual(first.timestamp_text, "2026-11-19 09:00:00.030")

    def test_error_multiline_continuation(self):
        error = next(entry for entry in self.result.entries if entry.level == "ERROR")
        self.assertEqual(error.continuation_lines, 1)
        self.assertIn("Element name 'link4'", error.raw)

    def test_param_colon_fields(self):
        entry = next(
            entry for entry in self.result.entries if entry.module == "CommandScheduler::init_loop"
        )
        self.assertEqual(entry.fields.get("param:angle"), "30.0")
        self.assertEqual(entry.fields.get("param:axis"), "z")

    def test_banner_and_spaced_values(self):
        banner = next(entry for entry in self.result.entries if "LOG START" in entry.raw)
        self.assertNotIn("START", banner.fields)
        entry = next(
            entry
            for entry in self.result.entries
            if entry.raw.startswith("[2026-11-19 09:00:00.035]")
        )
        self.assertEqual(entry.fields.get("q"), "0.08800")
        self.assertEqual(entry.fields.get("joint_num"), "8")

    def test_joint_angle_block_continuation(self):
        entry = next(
            entry for entry in self.result.entries if entry.module == "MuJoCoViewer::drawJointAngles"
        )
        self.assertGreaterEqual(entry.continuation_lines, 4)
        self.assertIn("Joint Angles", entry.raw)
        self.assertIn("J0", entry.fields)
        self.assertIn("J4", entry.fields)
        self.assertEqual(self.result.entries[-1].module, "saveWindowState")

    def test_table_header_and_border_skipped(self):
        raws = [entry.raw for entry in self.result.entries]
        self.assertFalse(any(raw.startswith("+---") for raw in raws))
        self.assertFalse(any(raw.startswith("| # |") for raw in raws))


class FormatterSequenceTests(unittest.TestCase):
    """tclog formatters.hpp 的 Eigen/vector/Span 序列输出。"""

    CONTENT = """\
[2026-11-19 10:00:00.000][info] [CommandScheduler::init_loop] param:goal=0,0,0,0,0,0
[2026-11-19 10:00:00.010][info] [Math] q=0.1, 0.2, 0.3
[2026-11-19 10:00:00.020][info] [Math] tf:
1.0, 0.0, 0.0, 0.5,
0.0, 1.0, 0.0, 0.6,
0.0, 0.0, 1.0, 0.7,
0.0, 0.0, 0.0, 1.0
[2026-11-19 10:00:00.030][info] [Math] tcp=(-0.1088, -0.1003, -0.4977)
[2026-11-19 10:00:00.040][info] [Math] sci=1e-3, 2.0E+4, -3.5
[2026-11-19 10:00:00.050][info] [Math] done
"""

    @classmethod
    def setUpClass(cls):
        cls.result = parse_bytes(cls.CONTENT.encode("utf-8"))

    def test_one_line_vector(self):
        entry = self.result.entries[0]
        self.assertEqual(entry.fields["param:goal"], "0,0,0,0,0,0")
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "CommandScheduler::init_loop")

    def test_short_vector_and_tuple(self):
        q_entry = next(entry for entry in self.result.entries if "q=" in entry.raw)
        self.assertEqual(q_entry.fields["q"], "0.1,0.2,0.3")
        tcp_entry = next(entry for entry in self.result.entries if "tcp=" in entry.raw)
        self.assertEqual(tcp_entry.fields["tcp"], "-0.1088,-0.1003,-0.4977")

    def test_multiline_matrix(self):
        entry = next(entry for entry in self.result.entries if entry.raw.startswith("[2026-11-19 10:00:00.020]"))
        self.assertEqual(entry.continuation_lines, 4)
        self.assertEqual(
            entry.fields["tf"],
            "1.0,0.0,0.0,0.5,0.0,1.0,0.0,0.6,0.0,0.0,1.0,0.7,0.0,0.0,0.0,1.0",
        )

    def test_scientific_notation(self):
        entry = next(entry for entry in self.result.entries if "sci=" in entry.raw)
        self.assertEqual(entry.fields["sci"], "1e-3,2.0E+4,-3.5")

    def test_sequence_extraction_does_not_swallow_next_entry(self):
        entry = self.result.entries[-1]
        self.assertEqual(entry.message, "done")
        self.assertEqual(entry.continuation_lines, 0)


class LoutLogTests(unittest.TestCase):
    """适配 samples/LOUT 的方括号标签与多行数值块格式。"""

    CONTENT = """\
[2026-09-21 20:06:32.763] [codeit] server parse cmd 8115 : {PushStatus --rcmtop_light=0 --rcmarm_light=262144 --trocar_light=2||PushStatus}
[2026-09-21 20:06:32.800] [codeit] server parse cmd 8116 : {PushStatus||PushStatus||PushStatus||PushStatus --mode_id=3 --master_map_id=3 --master_5G_id=7||PushStatus||PushStatus --mode_id=5 --master_map_id=5 --master_5G_id=8||PushStatus}
[2026-09-21 20:06:32.900] [codeit] server parse cmd 8117 : {UEmpty||UEmpty||JogTYLN --increase_count=100  --vel={0,0.02,0,0,0,0 } --direction=-1||UEmpty}
[2026-09-21 20:08:00.070] [Info] SubLoop ce_invoke_list length = 0 cmdSubId:0
[2026-09-22 07:48:18.392] [instrument][info] model 4, instrument motor move back home sucessfully
[instrument][error] model 3, adaptor install, move back home failed
[2026-09-22 07:48:46.417] [warn][/home/zhaowr/work/YC200_PSM/src/Common/src/multimodelfunc.cpp:268] model 3, used time 368 us
[2026-09-22 08:15:48.528] [plateUD_info]  count: 1701 sendCurrents[0]= 0 停止信号,使用递减函数
[2026-09-23 11:13:41.953] [codeit]function error or checkMotion faile-----
[2026-09-22 08:34:23.420] [info]  joint_pos_start:
[2026-09-22 08:34:23.420] 0.332108
[2026-09-22 08:34:23.420] -0.0080529
[2026-09-22 08:34:23.420] -2.27273e-06
[2026-09-22 08:34:23.420]
[2026-09-22 08:35:00.000] [info] done
[2026-09-21 20:08:00.101]
RT BIG 9277 --subcmd_index: 0 finished, spend 31 counts
       9277 --subcmd_index: 0 --return code: 0
"""

    @classmethod
    def setUpClass(cls):
        cls.result = parse_bytes(cls.CONTENT.encode("utf-8"))

    def entry(self, message_part: str):
        return next(entry for entry in self.result.entries if message_part in entry.message)

    def test_codeit_tag_and_fields(self):
        entry = self.result.entries[0]
        self.assertEqual(entry.module, "codeit")
        self.assertEqual(entry.level, "OTHER")
        self.assertIn("server parse cmd 8115", entry.message)
        self.assertEqual(entry.fields["cmd_id"], "8115")
        self.assertEqual(entry.fields["model_count"], "2")
        self.assertEqual(entry.fields["m0.cmd"], "PushStatus")
        self.assertEqual(entry.fields["m0.rcmtop_light"], "0")
        self.assertEqual(entry.fields["m0.rcmarm_light"], "262144")
        self.assertEqual(entry.fields["m0.trocar_light"], "2")
        self.assertEqual(entry.fields["m1.cmd"], "PushStatus")

    def test_codeit_models_split_by_pipe(self):
        entry = self.entry("parse cmd 8116")
        self.assertEqual(entry.fields["model_count"], "7")
        self.assertEqual(entry.fields["m3.cmd"], "PushStatus")
        self.assertEqual(entry.fields["m3.mode_id"], "3")
        self.assertEqual(entry.fields["m3.master_map_id"], "3")
        self.assertEqual(entry.fields["m3.master_5G_id"], "7")
        self.assertEqual(entry.fields["m5.mode_id"], "5")
        self.assertEqual(entry.fields["m5.master_5G_id"], "8")
        self.assertEqual(entry.fields["m1.cmd"], "PushStatus")

    def test_codeit_array_params(self):
        entry = self.entry("parse cmd 8117")
        self.assertEqual(entry.fields["m2.cmd"], "JogTYLN")
        self.assertEqual(entry.fields["m2.increase_count"], "100")
        self.assertEqual(entry.fields["m2.vel"], "0,0.02,0,0,0,0")
        self.assertEqual(entry.fields["m2.direction"], "-1")

    def test_instrument_tag_with_level(self):
        entry = self.entry("instrument motor move back home")
        self.assertEqual(entry.level, "INFO")
        self.assertEqual(entry.module, "instrument")
        error = self.entry("adaptor install")
        self.assertEqual(error.level, "ERROR")
        self.assertEqual(error.module, "instrument")
        self.assertIsNotNone(error.timestamp)

    def test_warn_source_location(self):
        entry = self.entry("used time 368 us")
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.module, "multimodelfunc.cpp:268")
        self.assertIn("multimodelfunc.cpp:268", entry.fields["source"])

    def test_plate_info_tag_is_module(self):
        entry = self.entry("停止信号")
        self.assertEqual(entry.module, "plateUD_info")
        self.assertTrue(entry.message.startswith("count: 1701"))

    def test_codeit_message_level_not_module(self):
        entry = self.entry("checkMotion")
        self.assertEqual(entry.module, "codeit")
        self.assertEqual(entry.level, "ERROR")

    def test_numeric_block_merged(self):
        entry = self.entry("joint_pos_start:")
        self.assertEqual(entry.continuation_lines, 4)
        self.assertIn("0.332108", entry.raw)
        self.assertIn("-2.27273e-06", entry.raw)

    def test_bare_timestamp_block_merged(self):
        entry = self.entry("RT BIG 9277")
        self.assertEqual(entry.continuation_lines, 2)
        self.assertEqual(entry.timestamp_text, "2026-09-21 20:08:00.101")
        self.assertIn("--return code: 0", entry.raw)


class RobustnessTests(unittest.TestCase):
    def test_empty_file(self):
        result = parse_bytes(b"")
        self.assertEqual(result.entries, [])
        self.assertEqual(result.encoding, "utf-8")

    def test_binary_rejected(self):
        with self.assertRaises(BinaryFileError):
            parse_bytes(b"\x00\x01\x02\x03" * 2048)

    def test_encrypted_file_detected(self):
        header = b"\x62\x14#et\x00\x8c\x01\x00\x00E-SafeNet\x00LOCK\x00\x00" + b"\x00" * 256
        with self.assertRaises(EncryptedFileError) as context:
            parse_bytes(header)
        self.assertIn("E-SafeNet", str(context.exception))
        self.assertIn("run_loglens.pyw", str(context.exception))

    def test_entry_cap_keeps_latest(self):
        content = "".join(f"2026-11-19 09:00:{i:02d} INFO core line {i}\n" for i in range(10))
        with mock.patch.object(parser_module, "MAX_ENTRIES", 5):
            result = parse_bytes(content.encode("utf-8"))
        self.assertEqual(len(result.entries), 5)
        self.assertTrue(result.truncated)
        self.assertIn("上限", result.truncation_reason)
        self.assertEqual([entry.message for entry in result.entries],
                         [f"core line {i}" for i in range(5, 10)])

    def test_time_window_parse(self):
        content = "".join(
            f"2026-11-19 09:00:{i:02d} INFO core line {i}\n" for i in range(10)
        )
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        handle.write(content.encode("utf-8"))
        handle.close()
        try:
            result = parse_file(
                handle.name,
                time_start=datetime(2026, 11, 19, 9, 0, 3),
                time_end=datetime(2026, 11, 19, 9, 0, 6),
            )
            with mock.patch.object(parser_module, "MAX_ENTRIES", 2):
                limited = parse_file(
                    handle.name,
                    time_start=datetime(2026, 11, 19, 9, 0, 3),
                    time_end=datetime(2026, 11, 19, 9, 0, 6),
                )
        finally:
            os.unlink(handle.name)

        self.assertEqual(
            [entry.message for entry in result.entries],
            [f"core line {i}" for i in range(3, 7)],
        )
        self.assertEqual(result.first_timestamp, datetime(2026, 11, 19, 9, 0, 3))
        self.assertEqual(result.last_timestamp, datetime(2026, 11, 19, 9, 0, 6))
        self.assertEqual(
            result.source_first_timestamp, datetime(2026, 11, 19, 9, 0, 0)
        )
        self.assertEqual(
            result.source_last_timestamp, datetime(2026, 11, 19, 9, 0, 9)
        )
        self.assertFalse(result.truncated)
        self.assertEqual(len(limited.entries), 2)
        self.assertTrue(limited.truncated)
        self.assertIn("范围内共 4 条", limited.truncation_reason)

    def test_tail_scan_keeps_recent_and_full_span(self):
        total = 500
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
            with mock.patch.object(parser_module, "MAX_ENTRIES", 50), mock.patch.object(
                parser_module, "TAIL_SCAN_THRESHOLD", 1024
            ), mock.patch.object(parser_module, "READ_BUFFER_BYTES", 4096):
                result = parse_file(handle.name)
        finally:
            os.unlink(handle.name)

        self.assertEqual(result.scan_mode, "tail")
        self.assertEqual(len(result.entries), 50)
        self.assertEqual(result.entries[0].message, "core line 450")
        self.assertEqual(result.entries[-1].message, "core line 499")
        self.assertEqual(result.total_lines, total)
        self.assertTrue(result.truncated)
        self.assertIn("文件时间范围", result.truncation_reason)
        self.assertEqual(result.first_timestamp, base + timedelta(seconds=450))
        self.assertEqual(result.last_timestamp, base + timedelta(seconds=499))
        self.assertEqual(result.source_first_timestamp, base)
        self.assertEqual(result.source_last_timestamp, base + timedelta(seconds=499))

    def test_time_window_stops_early_after_end(self):
        total = 5000
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
            with mock.patch.object(parser_module, "RANGE_EARLY_STOP_STREAK", 10):
                result = parse_file(
                    handle.name,
                    time_start=base,
                    time_end=base + timedelta(seconds=5),
                )
        finally:
            os.unlink(handle.name)

        self.assertEqual(
            [entry.message for entry in result.entries],
            [f"core line {index}" for index in range(6)],
        )
        self.assertEqual(result.scan_mode, "range")
        self.assertLess(result.total_lines, total)
        self.assertEqual(result.last_timestamp, base + timedelta(seconds=5))
        self.assertEqual(
            result.source_last_timestamp, base + timedelta(seconds=total - 1)
        )

    def test_cancel(self):
        content = "".join(f"2026-11-19 09:00:00 INFO core line {i}\n" for i in range(5000))
        with self.assertRaises(ParseCancelled):
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
            handle.write(content.encode("utf-8"))
            handle.close()
            try:
                parse_file(handle.name, should_cancel=lambda: True)
            finally:
                os.unlink(handle.name)

    def test_progress_called(self):
        progress_calls = []
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        try:
            handle.write(b"2026-11-19 09:00:00 INFO core ok\n")
            handle.close()
            parse_file(handle.name, progress=lambda *args: progress_calls.append(args))
        finally:
            os.unlink(handle.name)
        self.assertTrue(progress_calls)
        self.assertEqual(progress_calls[-1][0], progress_calls[-1][1])


if __name__ == "__main__":
    unittest.main()
