#!/usr/bin/env python3
"""
指令模拟服务器（TCP版）
接收并打印工具发送的指令（支持 InstTool 协议格式和纯文本）

协议格式:
  [4字节数据长度][36字节填充][UTF-8指令数据]

用法:
  python cmd_simulator.py              # 默认端口 7866
  python cmd_simulator.py --port 5866
"""

import argparse
import socket
import struct
import threading
from datetime import datetime


# ==================== 指令接收 ====================
def handle_client(conn, addr):
    """处理一个 TCP 客户端连接"""
    client_ip = addr[0]
    print(f"\n{'='*60}")
    print(f"[+] 连接来自 {client_ip}:{addr[1]}  {datetime.now().strftime('%H:%M:%S.%f')}")
    print(f"{'='*60}")

    conn.settimeout(0.5)
    buffer = b""
    cmd_count = 0

    try:
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except (ConnectionResetError, OSError):
                break

            if not data:
                break

            buffer += data

            # 尝试按协议格式解析
            while len(buffer) >= 40:
                data_len = struct.unpack("<I", buffer[:4])[0]
                # 跳过 40 字节头
                if len(buffer) >= 40 + data_len:
                    payload = buffer[40:40 + data_len]
                    buffer = buffer[40 + data_len:]

                    text = payload.decode("utf-8", errors="replace").strip("\x00").strip()
                    if text:
                        cmd_count += 1
                        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"\n  [{now}] 收到指令 #{cmd_count} ({data_len}B):")
                        print(f"    {text}")
                        print()
                else:
                    # 数据未收全，等待更多
                    break

            # 防内存溢出
            if len(buffer) > 1_000_000:
                buffer = b""

    except Exception as e:
        print(f"  [!] 异常: {type(e).__name__}: {e}")
    finally:
        print(f"[-] 连接关闭 {client_ip}:{addr[1]}  (共接收 {cmd_count} 条指令)")
        try:
            conn.close()
        except Exception:
            pass


# ==================== 主函数 ====================
def main():
    parser = argparse.ArgumentParser(description="指令模拟 TCP 服务器")
    parser.add_argument("--port", type=int, default=7866, help="监听端口 (默认 7866)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(10)

    print(f"{'='*60}")
    print(f"  📡 指令模拟 TCP 服务器启动")
    print(f"  监听: {args.host}:{args.port}")
    print(f"  解析协议: [4字节长度][36字节填充][数据]")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  在本机工具中设置:")
    print(f"    IP:   <本服务器的局域网IP>")
    print(f"    端口: {args.port}")
    print(f"{'='*60}")
    print(f"  按 Ctrl+C 停止")
    print(f"{'='*60}")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        print("\n[!] 服务器关闭")
    finally:
        server.close()


if __name__ == "__main__":
    main()
