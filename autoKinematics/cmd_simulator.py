#!/usr/bin/env python3
"""
指令模拟服务器（TCP版）
接收并打印工具发送的指令，按 protocol 格式回复模拟响应

协议格式:
  [4字节数据长度][36字节填充][UTF-8指令数据]

用法:
  python cmd_simulator.py              # 默认端口 7866
  python cmd_simulator.py --port 5866
  python cmd_simulator.py --delay 0.1  # 每条回复间隔
"""

import argparse
import socket
import struct
import threading
import time
from datetime import datetime

CMD_INDEX = 0
SHUTDOWN_FLAG = False


def _encode_message(data: str) -> bytes:
    """按协议格式编码: 4字节长度 + 36字节填充 + 数据"""
    data_bytes = data.encode("utf-8")
    return struct.pack("<I", len(data_bytes)) + bytes([0] * 36) + data_bytes


def _build_response(model_index: int) -> str:
    """构建一条模拟回复"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return (
        f"[{now}] [codeit]cmd {CMD_INDEX} subcmd_index:{model_index} "
        f"return code   :1 return message:"
    )


def handle_client(conn, addr, delay: float ,model: int):
    """处理一个 TCP 客户端连接"""
    global CMD_INDEX
    client_ip = addr[0]
    print(f"\n{'='*60}")
    print(f"[+] 连接来自 {client_ip}:{addr[1]}  {datetime.now().strftime('%H:%M:%S.%f')}")
    print(f"{'='*60}")

    global SHUTDOWN_FLAG
    conn.settimeout(0.5)
    buffer = b""
    cmd_count = 0

    try:
        while not SHUTDOWN_FLAG:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except (ConnectionResetError, OSError):
                break

            if not data:
                break

            buffer += data

            while len(buffer) >= 40:
                data_len = struct.unpack("<I", buffer[:4])[0]
                if len(buffer) < 40 + data_len:
                    break

                payload = buffer[40:40 + data_len]
                buffer = buffer[40 + data_len:]

                text = payload.decode("utf-8", errors="replace").strip("\x00").strip()
                if not text:
                    continue

                cmd_count += 1
                CMD_INDEX += 1
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"\n  [{now}] 收到指令 #{cmd_count} ({data_len}B):")
                print(f"    {text}")

                model_count = model
                print(f"    -> 回复 {model_count} 条 (cmd_index={CMD_INDEX})")

                for m in range(model_count):
                    resp_text = _build_response(m)
                    conn.sendall(_encode_message(resp_text))
                    if delay > 0:
                        time.sleep(delay)
                    print(f"       [{m}/{model_count-1}] {resp_text}")

                print()

            if len(buffer) > 1_000_000:
                buffer = b""

    except Exception as e:
        print(f"  [!] 异常: {type(e).__name__}: {e}")
    finally:
        print(f"[-] 连接关闭 {client_ip}:{addr[1]} (共接收 {cmd_count} 条指令)")
        try:
            conn.close()
        except Exception:
            pass


# ==================== 主函数 ====================
def main():
    parser = argparse.ArgumentParser(description="指令模拟 TCP 服务器")
    parser.add_argument("--port", type=int, default=7866, help="监听端口 (默认 7866)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--model", type=int,default=7, help="监听地址")
    parser.add_argument("--delay", type=float, default=0.1, help="每条回复间隔秒数")
    args = parser.parse_args()

    global SHUTDOWN_FLAG
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(10)
    server.settimeout(1.0)  # 1秒超时，让 accept 能被中断打断

    print(f"{'='*60}")
    print(f"  📡 指令模拟 TCP 服务器启动")
    print(f"  监听: {args.host}:{args.port}")
    print(f"  回复间隔: {args.delay}s")
    print(f"  仿真model: {args.model}个")
    print(f"  协议: [4字节长度][36字节填充][UTF-8数据]")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  本机工具连接设置:")
    print(f"    IP:   <本服务器IP>")
    print(f"    端口: {args.port}")
    print(f"{'='*60}")
    print(f"  按 Ctrl+C 停止")
    print(f"{'='*60}")

    try:
        while not SHUTDOWN_FLAG:
            try:
                conn, addr = server.accept()
                t = threading.Thread(
                    target=handle_client,
                    args=(conn, addr, args.delay, args.model),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\n[!] 正在关闭...")
    finally:
        SHUTDOWN_FLAG = True
        server.close()
        print("服务器已停止")


if __name__ == "__main__":
    main()
