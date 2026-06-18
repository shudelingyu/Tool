#!/usr/bin/env python3
"""
指令模拟 SSH 服务器
在另一台电脑上运行，接收并打印工具发送的指令，用于验证指令格式
使用 paramiko 实现完整 SSH 协议握手

用法:
  python cmd_simulator.py              # 默认端口 7788
  python cmd_simulator.py --port 12345
  python cmd_simulator.py --key server_key  # 指定密钥文件

连接测试（本机工具）：
  IP 填模拟服务器的 IP，端口 7788，用户名密码随便填
"""

import argparse
import logging
import os
import socket
import sys
import threading
from datetime import datetime

import paramiko

logging.basicConfig(level=logging.WARNING)
paramiko_logger = logging.getLogger("paramiko")
paramiko_logger.setLevel(logging.WARNING)


# ==================== SSH 服务端 ====================
class CmdEchoHandler(paramiko.ServerInterface):
    """SSH 服务端，接收到的命令打印到控制台"""

    def __init__(self, client_ip):
        self.client_ip = client_ip

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_auth_none(self, username):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password,publickey,none"

    def check_channel_shell_request(self, channel):
        return True

    def check_channel_exec_request(self, channel, command):
        if command:
            _print_cmd(command)
        try:
            channel.sendall(b"OK\n")
        except OSError:
            pass
        try:
            channel.shutdown_write()
            channel.send_exit_status(0)
        except OSError:
            pass
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


def handle_connection(conn, addr):
    """处理一个 SSH 连接"""
    client_ip = addr[0]
    print(f"\n{'='*60}")
    print(f"[+] SSH 连接来自 {client_ip}:{addr[1]}  {datetime.now().strftime('%H:%M:%S.%f')}")
    print(f"{'='*60}")

    transport = None
    try:
        transport = paramiko.Transport(conn)
        transport.add_server_key(HOST_KEY)

        handler = CmdEchoHandler(client_ip)
        transport.start_server(server=handler)

        # 循环接受通道（支持 shell 会话和多次 exec_command）
        while transport.is_active():
            channel = transport.accept(10)
            if channel is None:
                continue

            # 通道已建立，尝试读取数据（shell 模式）
            channel.settimeout(0.5)
            buffer = b""
            while True:
                try:
                    data = channel.recv(4096)
                except socket.timeout:
                    break
                except (EOFError, OSError):
                    break
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        _print_cmd(line)
                        try:
                            channel.sendall(b"OK\n")
                        except OSError:
                            break
                if len(buffer) > 8192:
                    _print_cmd(buffer)
                    buffer = b""

    except EOFError:
        pass
    except OSError:
        pass
    except Exception as e:
        print(f"  [!] 异常: {type(e).__name__}: {e}")
    finally:
        if transport:
            try:
                transport.close()
            except Exception:
                pass
        print(f"[-] 连接关闭 {client_ip}:{addr[1]}")


# ==================== 指令格式化打印 ====================
def _print_cmd(data: bytes):
    """直接打印收到的数据"""
    try:
        text = data.decode("utf-8", errors="replace").strip().strip("\x00")
    except Exception:
        text = repr(data)
    if not text:
        return
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"  [{now}] {text}")


# 生成或加载 SSH 主机密钥
HOST_KEY = paramiko.RSAKey.generate(2048)


# ==================== 主函数 ====================
def main():
    parser = argparse.ArgumentParser(description="指令模拟 SSH 服务器")
    parser.add_argument("--port", type=int, default=7788, help="监听端口 (默认 7788)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(10)

    print(f"{'='*60}")
    print(f"  📡 指令模拟 SSH 服务器启动")
    print(f"  监听: {args.host}:{args.port}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  在本机工具中设置:")
    print(f"    IP:   <本服务器的局域网IP>")
    print(f"    端口: {args.port}")
    print(f"    用户名/密码: 任意")
    print(f"{'='*60}")
    print(f"  按 Ctrl+C 停止")
    print(f"{'='*60}")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_connection,
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

