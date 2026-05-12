import paramiko
import socket
import sys
import os
import time
import threading
import select

# Windows 和 Linux 平台兼容性处理
if sys.platform.startswith('win'):
    import msvcrt
else:
    import tty
    import termios

class SSHClient:
    def __init__(self, hostname, username, password=None, key_filename=None, port=22):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.port = port
        self.client = None
        self.channel = None
        self.running = False
        
    def connect(self):
        """连接到SSH服务器"""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            self.client.connect(
                hostname=self.hostname,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                port=self.port,
                timeout=10
            )
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False
    
    def start_interactive(self):
        """启动交互式会话"""
        if not self.connect():
            return False
            
        # 创建shell通道
        self.channel = self.client.invoke_shell(term='xterm-256color')
        self.running = True
        
        print("已连接到远程服务器。输入 'quit' 退出会话。")
        
        # 启动输出线程
        output_thread = threading.Thread(target=self._handle_output)
        output_thread.daemon = True
        output_thread.start()
        
        # 处理输入
        self._handle_input()
        
        return True
    
    def _handle_output(self):
        """处理远程输出"""
        try:
            while self.running:
                # 检查是否有数据可读
                if self.channel.recv_ready():
                    data = self.channel.recv(1024).decode('utf-8', errors='ignore')
                    sys.stdout.write(data)
                    sys.stdout.flush()
                
                # 检查连接是否关闭
                if self.channel.exit_status_ready():
                    print("\n远程连接已关闭")
                    self.running = False
                    break
                    
                time.sleep(0.01)
        except Exception as e:
            print(f"\n输出处理错误: {e}")
            self.running = False
    
    def _handle_input(self):
        """处理本地输入"""
        try:
            # 设置终端（仅Linux/Unix）
            if not sys.platform.startswith('win'):
                old_attr = termios.tcgetattr(sys.stdin)
                tty.setraw(sys.stdin.fileno())
            
            input_buffer = ""
            
            while self.running:
                # Windows 输入处理
                if sys.platform.startswith('win'):
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        
                        # 处理特殊键
                        if char == b'\x08':  # Backspace
                            if len(input_buffer) > 0:
                                input_buffer = input_buffer[:-1]
                                # 发送退格序列
                                self.channel.send('\x08 \x08')
                        elif char == b'\r':  # Enter
                            self.channel.send('\r')
                            # 检查是否是退出命令
                            if input_buffer.strip().lower() == 'quit':
                                print("\n正在退出...")
                                self.running = False
                                break
                            input_buffer = ""
                        elif char == b'\x03':  # Ctrl+C - 忽略
                            pass
                        else:
                            # 普通字符
                            try:
                                char_str = char.decode('utf-8')
                                input_buffer += char_str
                                self.channel.send(char_str)
                            except:
                                pass
                
                # Linux/Unix 输入处理
                else:
                    # 使用select检查是否有输入
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        char = sys.stdin.read(1)
                        
                        # 处理特殊键
                        if ord(char) == 127:  # Backspace
                            if len(input_buffer) > 0:
                                input_buffer = input_buffer[:-1]
                                # 发送退格序列
                                self.channel.send('\x7f')
                        elif char == '\r' or char == '\n':  # Enter
                            self.channel.send('\r')
                            # 检查是否是退出命令
                            if input_buffer.strip().lower() == 'quit':
                                print("\n正在退出...")
                                self.running = False
                                break
                            input_buffer = ""
                        elif ord(char) == 3:  # Ctrl+C - 忽略
                            pass
                        else:
                            # 普通字符
                            input_buffer += char
                            self.channel.send(char)
                
                time.sleep(0.01)
                
        except KeyboardInterrupt:
            # 捕获Ctrl+C但不退出，只是忽略
            print("\n(提示: 输入 'quit' 退出会话)")
        except Exception as e:
            print(f"\n输入处理错误: {e}")
        finally:
            # 恢复终端设置（仅Linux/Unix）
            if not sys.platform.startswith('win'):
                try:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attr)
                except:
                    pass
                
            self.close()
    
    def execute_command(self, command):
        """执行单个命令"""
        if not self.connect():
            return None, None
            
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode('utf-8', errors='ignore')
            error = stderr.read().decode('utf-8', errors='ignore')
            return output, error
        except Exception as e:
            return None, str(e)
        finally:
            self.close()
    
    def close(self):
        """关闭连接"""
        self.running = False
        if self.channel:
            self.channel.close()
        if self.client:
            self.client.close()

def main():
    """主函数"""
    print("SSH 交互式终端客户端")
    print("=" * 40)
    
    # 获取连接信息
    hostname = input("服务器地址: ").strip()
    if not hostname:
        print("必须提供服务器地址")
        return
        
    username = input("用户名: ").strip()
    if not username:
        print("必须提供用户名")
        return
        
    port_str = input("端口 (默认22): ").strip()
    port = int(port_str) if port_str else 22
    
    # 认证方式
    print("\n认证方式:")
    print("1. 密码认证")
    print("2. 密钥认证")
    auth_choice = input("选择 (1/2): ").strip()
    
    password = None
    key_filename = None
    
    if auth_choice == "1":
        password = input("密码: ").strip()
    elif auth_choice == "2":
        key_filename = input("密钥文件路径: ").strip()
    else:
        print("无效选择，使用密码认证")
        password = input("密码: ").strip()
    
    # 创建SSH客户端
    ssh_client = SSHClient(hostname, username, password, key_filename, port)
    
    # 连接模式选择
    print("\n连接模式:")
    print("1. 交互式终端")
    print("2. 执行单个命令")
    mode_choice = input("选择 (1/2): ").strip()
    
    if mode_choice == "2":
        command = input("输入要执行的命令: ").strip()
        output, error = ssh_client.execute_command(command)
        
        if output is not None:
            print("\n命令输出:")
            print(output)
        if error:
            print("\n错误信息:")
            print(error)
    else:
        # 交互式终端模式
        print("\n正在连接...")
        if ssh_client.start_interactive():
            print("会话已结束")
        else:
            print("连接失败")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序已退出")