import socket
import threading
import struct
import tkinter as tk
from tkinter import messagebox, ttk
import cv2
import time
import os
import logging
from datetime import datetime
import math 
from PIL import Image, ImageTk
import queue   

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 默认配置常量
DEFAULT_HOST = '192.168.11.11'
DEFAULT_PORT = 7899
DEFAULT_ERROR_PORT = 5868
PHOTOS_FOLDER = "photos"  # 照片保存文件夹

# 全局变量
s = None
error_thread = None
error_listener_running = True
current_host = DEFAULT_HOST
current_port = DEFAULT_PORT
current_error_port = DEFAULT_ERROR_PORT
error_connection_failed_count = 0
backlash = 0.0 

# ============ 修复频闪问题的完整代码 ============

# 全局变量
camera_preview_window = None
camera_running = False
camera_thread = None
camera_cap = None
preview_label = None
current_photo_image = None  # 保持图像引用，防止被垃圾回收
frame_queue = queue.Queue(maxsize=2)  # 帧队列，避免堆积
selected_camera_index = None  # 当前选中的相机索引（稍后初始化）

def open_camera_preview():
    """打开相机预览窗口"""
    global camera_preview_window, camera_running, preview_label
    
    if camera_preview_window is not None and camera_preview_window.winfo_exists():
        camera_preview_window.lift()
        camera_preview_window.focus_force()
        return
    
    camera_preview_window = tk.Toplevel(root)
    camera_preview_window.title("相机实时预览")
    camera_preview_window.geometry("1040x560")
    camera_preview_window.protocol("WM_DELETE_WINDOW", stop_camera_preview)
    
    # 相机选择区域
    camera_select_frame = tk.Frame(camera_preview_window)
    camera_select_frame.pack(fill=tk.X, padx=10, pady=5)
    
    tk.Label(camera_select_frame, text="选择相机:", font=("Arial", 10)).pack(side=tk.LEFT, padx=5)
    
    camera_index_combo = ttk.Combobox(
        camera_select_frame, 
        textvariable=selected_camera_index,
        values=[str(i) for i in range(5)],
        width=5,
        state="readonly"
    )
    camera_index_combo.pack(side=tk.LEFT, padx=5)
    camera_index_combo.bind("<<ComboboxSelected>>", on_camera_index_changed)
    
    # 视频显示区域 - 固定大小避免重绘
    video_frame = tk.Frame(camera_preview_window, bg="black", width=1040, height=520)
    video_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    video_frame.pack_propagate(False)  # 禁止自动调整大小
    
    # 创建 Label 时指定固定尺寸
    preview_label = tk.Label(
        video_frame, 
        bg="black",
        width=1040,
        height=520
    )
    preview_label.pack(fill=tk.BOTH, expand=True)
    preview_label.image = None  # 预先绑定属性
    
    camera_preview_window.status_label = tk.Label(camera_preview_window, text="状态: 准备就绪", fg="gray")
    camera_preview_window.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)
    
    camera_preview_window.after(100, lambda: start_camera_stream())

def on_camera_index_changed(event=None):
    """相机索引改变时重新启动相机"""
    if camera_running:
        stop_camera_stream()
        camera_preview_window.after(100, lambda: start_camera_stream())
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 已切换到相机 {selected_camera_index.get()}")
    
    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 相机预览窗口已打开")

def start_camera_stream():
    """开始相机视频流"""
    global camera_running, camera_thread, camera_cap, camera_preview_window
    
    if camera_running:
        add_to_message_display("相机已在运行中")
        return
    
    camera_index = selected_camera_index.get()
    
    camera_cap = cv2.VideoCapture(camera_index)
    
    if not camera_cap.isOpened():
        messagebox.showerror("错误", f"无法打开相机 {camera_index}")
        camera_preview_window.status_label.config(text="状态: 打开失败", fg="red")
        return
    
    # 固定分辨率，避免尺寸变化导致闪烁
    camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1040)
    camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 520)
    camera_cap.set(cv2.CAP_PROP_FPS, 60)
    
    # 使用 MJPEG 加速（如果相机支持）
    camera_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    
    camera_running = True
    camera_preview_window.status_label.config(text="状态: 运行中", fg="green")
    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 相机已启动")
    
    # 启动采集线程
    camera_thread = threading.Thread(target=camera_capture_thread, daemon=True)
    camera_thread.start()
    
    # 启动 GUI 更新（在主线程中）
    update_preview_gui()

def stop_camera_stream():
    """停止相机视频流"""
    global camera_running, camera_cap, camera_preview_window, current_photo_image
    
    camera_running = False
    
    if camera_cap is not None:
        camera_cap.release()
        camera_cap = None
    
    # 清空队列
    while not frame_queue.empty():
        try:
            frame_queue.get_nowait()
        except:
            break
    
    if camera_preview_window and hasattr(camera_preview_window, 'status_label'):
        camera_preview_window.status_label.config(text="状态: 已停止", fg="gray")
    
    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 相机已停止")

def camera_capture_thread():
    """相机采集线程（只负责采集，不更新 GUI）"""
    global camera_running, camera_cap, frame_queue
    
    while camera_running and camera_cap is not None:
        ret, frame = camera_cap.read()
        
        if not ret or frame is None:
            time.sleep(0.01)
            continue
        
        # 转换颜色空间 BGR -> RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # 转换为 PIL 格式
        img = Image.fromarray(frame_rgb)
        
        # 放入队列（如果队列满了就跳过这帧，避免堆积）
        if frame_queue.full():
            try:
                frame_queue.get_nowait()  # 丢弃旧帧
            except:
                pass
        
        try:
            frame_queue.put_nowait(img)
        except:
            pass
        
        # 不 sleep，让采集尽可能快，由 GUI 更新控制帧率

def update_preview_gui():
    """GUI 更新函数（在主线程中运行）"""
    global current_photo_image, preview_label, camera_running
    
    if not camera_running:
        return
    
    # 从队列获取最新帧
    try:
        img = frame_queue.get_nowait()
        
        # 转换为 PhotoImage
        current_photo_image = ImageTk.PhotoImage(image=img)
        
        # 保持引用防止被垃圾回收
        preview_label.image = current_photo_image
        
        # 更新 Label
        preview_label.config(image=current_photo_image)
        
    except queue.Empty:
        pass  # 没有新帧，不更新
    
    # 使用 after 定时更新，约 30 FPS
    if camera_running:
        camera_preview_window.after(33, update_preview_gui)  # 33ms ≈ 30 FPS

def stop_camera_preview():
    """关闭预览窗口"""
    global camera_preview_window, camera_running, camera_cap, current_photo_image
    
    stop_camera_stream()
    current_photo_image = None
    
    if camera_preview_window is not None:
        camera_preview_window.destroy()
        camera_preview_window = None
    
    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 相机预览窗口已关闭")



def create_photos_folder():
    """创建photos文件夹"""
    if not os.path.exists(PHOTOS_FOLDER):
        try:
            os.makedirs(PHOTOS_FOLDER)
            logger.info(f"已创建照片文件夹: {PHOTOS_FOLDER}")
            add_to_message_display(f"已创建照片文件夹: {PHOTOS_FOLDER}")
            return True
        except Exception as e:
            logger.error(f"创建照片文件夹失败: {e}")
            add_to_message_display(f"创建照片文件夹失败: {e}")
            return False
    return True

def encode_message(data):
    """编码消息为协议格式"""
    data_len = len(data)
    message_head_datalen = struct.pack('<I', data_len)
    message_head_other = bytes([0] * (40 - len(message_head_datalen)))
    message_data = data.encode('utf-8')
    return message_head_datalen + message_head_other + message_data

def error_listener():
    """错误消息监听器"""
    global error_listener_running, error_connection_failed_count
    
    error_connection_failed_count = 0  # 重置失败计数器
    
    while error_listener_running:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as es:
                es.settimeout(5)  # 设置超时
                es.connect((current_host, current_error_port))
                logger.info(f"已成功连接错误端口 {current_host}:{current_error_port}")
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 已连接错误端口")
                error_connection_failed_count = 0  # 连接成功，重置计数器
                
                while error_listener_running:
                    try:
                        data = es.recv(1024)
                        if not data:
                            add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 错误端口连接断开")
                            break
                        error_msg = data.decode('utf-8', errors='ignore')
                        logger.info(f"收到错误消息: {error_msg}")
                        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {error_msg}")
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if error_listener_running:
                            add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 错误监听接收异常: {e}")
                        break
        except Exception as e:
            if error_listener_running:
                error_connection_failed_count += 1
                # 只在第一次连接失败时显示详细错误，后续失败不重复显示
                if error_connection_failed_count == 1:
                    logger.error(f"错误消息连接出错: {e}")
                    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 错误端口连接失败")
                # 如果连续失败超过3次，减少重试频率
                time.sleep(10 if error_connection_failed_count > 3 else 3)

def connect_to_server():
    """连接到服务器"""
    global s, error_thread, error_listener_running, error_connection_failed_count
    global current_host, current_port, current_error_port
    
    # 从输入框获取新的连接参数
    new_host = host_var.get().strip()
    new_port = port_var.get().strip()
    new_error_port = error_port_var.get().strip()
    
    # 验证输入
    if not new_host:
        messagebox.showwarning("输入错误", "请输入服务器IP地址")
        return False
    
    try:
        new_port = int(new_port)
        if new_port < 1 or new_port > 65535:
            messagebox.showwarning("输入错误", "端口号必须在1-65535之间")
            return False
    except ValueError:
        messagebox.showwarning("输入错误", "请输入有效的端口号")
        return False
    
    try:
        new_error_port = int(new_error_port)
        if new_error_port < 1 or new_error_port > 65535:
            messagebox.showwarning("输入错误", "错误端口号必须在1-65535之间")
            return False
    except ValueError:
        messagebox.showwarning("输入错误", "请输入有效的错误端口号")
        return False
    
    # 更新全局变量
    current_host = new_host
    current_port = new_port
    current_error_port = new_error_port
    
    try:
        # 先关闭现有连接
        if s:
            try:
                s.close()
            except:
                pass
        
        # 停止错误监听线程
        error_listener_running = False
        if error_thread and error_thread.is_alive():
            error_thread.join(timeout=2)
        
        # 重新建立发送消息的socket连接
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)  # 设置连接超时
        s.connect((current_host, current_port))
        logger.info(f"已成功连接到 {current_host}:{current_port}")
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 已连接到 {current_host}:{current_port}")
        
        # 重置错误连接失败计数器
        error_connection_failed_count = 0
        
        # 重新启动错误消息监听线程
        error_listener_running = True
        error_thread = threading.Thread(target=error_listener, daemon=True)
        error_thread.start()
        
        # 更新状态
        update_connection_status(True)
        update_server_info()
        return True
        
    except socket.timeout:
        error_msg = f"连接超时: 无法连接到 {current_host}:{current_port}"
        logger.error(error_msg)
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        update_connection_status(False)
        return False
    except ConnectionRefusedError:
        error_msg = f"连接被拒绝: 服务器未启动或端口被占用"
        logger.error(error_msg)
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        update_connection_status(False)
        return False
    except Exception as e:
        error_msg = f"连接出错: {e}"
        logger.error(error_msg)
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        update_connection_status(False)
        return False

def reconnect():
    """重连功能"""
    add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 正在重新连接服务器...")
    reconnect_button.config(state=tk.DISABLED, text="连接中...")
    
    # 在单独的线程中执行重连，避免阻塞GUI
    def reconnect_thread():
        success = connect_to_server()
        
        # 在主线程中更新UI
        def update_ui():
            if success:
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 重连成功")
                reconnect_button.config(text="✅ 已连接", bg="#4CAF50")
            else:
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 重连失败")
                reconnect_button.config(text="🔁 重连", bg="#FF9800")
            
            # 5秒后恢复按钮状态
            root.after(3000, lambda: reconnect_button.config(state=tk.NORMAL))
        
        root.after(0, update_ui)
    
    # 启动重连线程
    threading.Thread(target=reconnect_thread, daemon=True).start()

def send_command(command):
    """发送命令"""
    global s
    
    # 检查连接状态
    if s is None:
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 连接未建立，请先重连")
        messagebox.showwarning("连接错误", "连接未建立，请先点击重连按钮")
        update_connection_status(False)
        return
    
    try:
        # 测试连接是否活跃
        s.settimeout(1)
        try:
            # 发送一个测试包
            s.send(b'')
        except:
            # 如果测试失败，尝试重新连接一次
            add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 连接测试失败，尝试重新发送")
        
        data = encode_message(command)
        s.sendall(data)
        logger.info(f"指令[{command}]发送成功")
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 已发送: {command}")
    except (socket.timeout, ConnectionError, OSError) as e:
        error_msg = f"发送指令[{command}]出错: 连接已断开"
        logger.error(error_msg)
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 发送失败: {command} - 连接已断开")
        update_connection_status(False)
        messagebox.showerror("连接错误", f"连接已断开，请重连后重试")
    except Exception as e:
        error_msg = f"发送指令[{command}]出错: {e}"
        logger.error(error_msg)
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 发送失败: {command} - {e}")
        messagebox.showerror("错误", error_msg)

# 修改send_movement_command函数（约第280行附近）

def send_movement_command(mode):
    """发送运动控制指令"""
    global backlash  # 如果需要全局使用
    
    try:
        # 获取距离值
        distance = distance_var.get().strip()
        if not distance:
            messagebox.showwarning("警告", "请输入距离值")
            return
        
        # 验证距离是否为数字
        try:
            distance_val = float(distance)
            distance_val = math.radians(distance_val)  # 度转弧度
        except ValueError:
            messagebox.showwarning("警告", "距离必须为数字")
            return
        
        # 获取循环次数
        try:
            cycles = int(cycle_var.get().strip())
            if cycles < 0:
                raise ValueError
        except Exception:
            messagebox.showwarning("警告", "循环次数必须为非负整数")
            return
        
        # 获取backlash值（可选的，默认0）
        backlash_str = backlash_var.get().strip()
        if not backlash_str:
            backlash_val = 0.0
        else:
            try:
                backlash_val = float(backlash_str)
                backlash_val = math.radians(backlash_val)  # 度转弧度
            except ValueError:
                messagebox.showwarning("警告", "回差必须为数字")
                return
        
        # 构建指令（包含循环次数和backlash）
        command = f"AirborneCalibration --mode={mode} --distance={distance_val} --cycles={cycles} --backlash={backlash_val}"
        
        # 发送指令
        send_command(command)
        
    except Exception as e:
        error_msg = f"发送运动指令出错: {e}"
        logger.error(error_msg)
        messagebox.showerror("错误", error_msg)
        

def update_connection_status(connected):
    """更新连接状态显示"""
    if connected:
        for btn in all_buttons:
            btn.config(state=tk.NORMAL)
    else:
        for btn in all_buttons:
            if btn != reconnect_button:  # 不禁用重连按钮
                btn.config(state=tk.DISABLED)
        
        # 更新重连按钮状态
        reconnect_button.config(text="🔁 重连", bg="#FF9800", state=tk.NORMAL)

def simple_capture(filename=None, camera_index=0, show_preview=False):
    """
    基础相机拍照功能
    :param filename: 保存的文件名，如果为None则自动生成
    :param camera_index: 相机索引（0通常为默认相机）
    :param show_preview: 是否显示预览
    :return: 是否成功
    """
    # 1. 创建相机对象
    cap = cv2.VideoCapture(camera_index)
    
    if not cap.isOpened():
        error_msg = f"错误：无法打开相机 {camera_index}"
        add_to_message_display(error_msg)
        add_to_message_display("请检查：")
        add_to_message_display("1. 相机是否正确连接")
        add_to_message_display("2. 其他程序是否占用了相机")
        add_to_message_display("3. 可以尝试使用 camera_index=1, 2, ...")
        logger.error(error_msg)
        return False
    
    # 2. 设置相机参数（可选）
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)  # 宽度
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)  # 高度
    cap.set(cv2.CAP_PROP_FPS, 30)           # 帧率
    # cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)      # 自动对焦
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 0.5)   # 亮度
    cap.set(cv2.CAP_PROP_CONTRAST, 0.5)     # 对比度
    
    # 3. 预热相机（丢弃前几帧）
    add_to_message_display("正在初始化相机...")
    for _ in range(5):
        ret, _ = cap.read()
        if not ret:
            add_to_message_display("相机初始化失败")
            cap.release()
            return False
        time.sleep(0.1)
    
    # 4. 拍照
    add_to_message_display("准备拍照...")
    time.sleep(0.3)  # 短暂延时
    
    ret, frame = cap.read()
    
    if not ret or frame is None:
        add_to_message_display("拍照失败！")
        cap.release()
        return False
    
    # 5. 保存照片
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{PHOTOS_FOLDER}/photo_{timestamp}.jpg"
    
    # 确保文件名有正确的扩展名
    if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
        filename += ".jpg"
    
    # 确保照片文件夹存在
    folder = os.path.dirname(filename)
    if folder and not os.path.exists(folder):
        try:
            os.makedirs(folder, exist_ok=True)
            add_to_message_display(f"已创建文件夹: {folder}")
        except Exception as e:
            add_to_message_display(f"创建文件夹失败: {e}")
            cap.release()
            return False
    
    success = cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    if success:
        height, width = frame.shape[:2]
        file_size = os.path.getsize(filename) / 1024  # KB
        add_to_message_display("✓ 拍照成功！")
        add_to_message_display(f"   文件名: {filename}")
        add_to_message_display(f"   尺寸: {width}x{height}")
        add_to_message_display(f"   文件大小: {file_size:.1f} KB")
        
        # 显示保存位置
        full_path = os.path.abspath(filename)
        add_to_message_display(f"   保存路径: {full_path}")
    else:
        add_to_message_display("✗ 保存照片失败！")
        add_to_message_display("   请检查文件路径和磁盘空间")
    
    # 6. 释放相机
    cap.release()
    
    if success:
        logger.info(f"照片保存成功: {filename}")
    else:
        logger.error("照片保存失败")
    
    return success

def take_photo():
    """拍照功能"""
    def capture_thread():
        photo_button.config(state=tk.DISABLED)
        camera_idx = selected_camera_index.get()
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 开始拍照（相机 {camera_idx}）...")
        
        try:
            if not create_photos_folder():
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 无法创建照片文件夹，拍照取消")
                photo_button.config(state=tk.NORMAL)
                return
            
            success = simple_capture(camera_index=camera_idx, show_preview=False)
            
            if success:
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 拍照完成")
            else:
                add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 拍照失败")
        
        except Exception as e:
            error_msg = f"拍照过程中发生错误: {e}"
            logger.error(error_msg)
            add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
            messagebox.showerror("拍照错误", error_msg)
        
        finally:
            photo_button.config(state=tk.NORMAL)
    
    threading.Thread(target=capture_thread, daemon=True).start()


def add_to_message_display(message):
    """添加消息到显示区域"""
    if 'message_text' in globals():
        message_text.insert(tk.END, f"{message}\n")
        message_text.see(tk.END)  # 自动滚动到底部

def send_custom_command():
    """发送自定义指令"""
    command = custom_command_entry.get().strip()
    if command:
        send_command(command)
        custom_command_entry.delete(0, tk.END)
    else:
        messagebox.showwarning("警告", "请输入有效的指令")

def on_close():
    """关闭程序"""
    global error_listener_running
    
    if messagebox.askokcancel("退出", "确定退出程序吗？"):
        error_listener_running = False
        try:
            if s:
                s.close()
        except:
            pass
        root.destroy()

# 创建 Tkinter 界面
root = tk.Tk()
root.title("InstTool")
root.geometry("750x700")  # 增加高度以容纳重连按钮
root.protocol("WM_DELETE_WINDOW", on_close)

# 初始化相机索引变量（在 root 创建之后）
selected_camera_index = tk.IntVar(value=0)

# 连接设置栏（放在最前面）
connection_frame = tk.LabelFrame(root, text="连接设置", padx=10, pady=5, fg="black")
connection_frame.pack(fill=tk.X, padx=10, pady=5)

# IP地址输入
ip_frame = tk.Frame(connection_frame)
ip_frame.pack(fill=tk.X, pady=2)
tk.Label(ip_frame, text="服务器IP:", fg="black", width=10).pack(side=tk.LEFT)
host_var = tk.StringVar(value=DEFAULT_HOST)
host_entry = tk.Entry(ip_frame, textvariable=host_var, width=20)
host_entry.pack(side=tk.LEFT, padx=5)

# 主端口输入
port_frame = tk.Frame(connection_frame)
port_frame.pack(fill=tk.X, pady=2)
tk.Label(port_frame, text="主端口:", fg="black", width=10).pack(side=tk.LEFT)
port_var = tk.StringVar(value=str(DEFAULT_PORT))
port_entry = tk.Entry(port_frame, textvariable=port_var, width=10)
port_entry.pack(side=tk.LEFT, padx=5)

# 错误端口输入
error_port_frame = tk.Frame(connection_frame)
error_port_frame.pack(fill=tk.X, pady=2)
tk.Label(error_port_frame, text="错误端口:", fg="black", width=10).pack(side=tk.LEFT)
error_port_var = tk.StringVar(value=str(DEFAULT_ERROR_PORT))
error_port_entry = tk.Entry(error_port_frame, textvariable=error_port_var, width=10)
error_port_entry.pack(side=tk.LEFT, padx=5)

# 连接控制栏
control_frame = tk.Frame(root, bg="#f0f0f0", padx=10, pady=5)
control_frame.pack(fill=tk.X, padx=0, pady=0)

# 服务器信息
server_info = tk.Label(
    control_frame,
    text=f"当前连接: {current_host}:{current_port}",
    bg="#f0f0f0",
    fg="black",
    font=("Arial", 9)
)
server_info.pack(side=tk.LEFT)

# 重连按钮
reconnect_button = tk.Button(
    control_frame,
    text="连接中...",
    command=reconnect,
    bg="#2196F3",
    fg="white",
    font=("Arial", 10, "bold"),
    width=12
)
reconnect_button.pack(side=tk.RIGHT, padx=5)

# 状态指示灯
status_light = tk.Canvas(control_frame, width=20, height=20, bg="#f0f0f0", highlightthickness=0)
status_circle = status_light.create_oval(2, 2, 18, 18, fill="gray")
status_light.pack(side=tk.RIGHT, padx=5)
status_label = tk.Label(control_frame, text="状态:", bg="#f0f0f0", fg="black")
status_label.pack(side=tk.RIGHT, padx=(0, 5))

# 更新状态信息显示
def update_server_info():
    server_info.config(text=f"当前连接: {current_host}:{current_port}")
    status_label.config(text=f"当前连接: {current_host}:{current_port} | 错误端口: {current_error_port} | 照片文件夹: {PHOTOS_FOLDER} | 距离单位: mm")

# 主框架
main_frame = tk.Frame(root, padx=10, pady=10)
main_frame.pack(fill=tk.BOTH, expand=True)

# 控制按钮区域
btn_frame = tk.LabelFrame(main_frame, text="控制命令", padx=10, pady=10, fg="black")
btn_frame.pack(fill=tk.X, pady=(0, 10))

# 第一行按钮布局
row1_frame = tk.Frame(btn_frame)
row1_frame.pack(fill=tk.X, pady=5)

# 定义第一行命令按钮
commands_row1 = [
    ("回零", "Homing", "#2196F3"),
    ("装适配器", "InstallAdaptor", "#2196F3"),
    ("装器械", "InstallInstrument", "#2196F3"),
    ("相机预览", open_camera_preview, "#4CAF50"),  # 新增相机预览按钮
    ("拍照", take_photo, "#2196F3")  # 拍照按钮
]

# 创建按钮
all_buttons = []
for i, (text, cmd, color) in enumerate(commands_row1):
    if callable(cmd):  # 如果是函数
        btn = tk.Button(
            row1_frame,
            text=text,
            width=10,
            bg=color,
            fg="white",
            font=("Arial", 10, "bold"),
            command=cmd
        )
    else:  # 如果是命令字符串
        btn = tk.Button(
            row1_frame,
            text=text,
            width=10,
            bg=color,
            fg="white",
            font=("Arial", 10, "bold"),
            command=lambda c=cmd: send_command(c)
        )
    btn.grid(row=0, column=i, padx=5, sticky="ew")
    all_buttons.append(btn)
    
    # 保存拍照按钮引用
    if text == "拍照":
        photo_button = btn

# 设置列权重
for i in range(4):
    row1_frame.columnconfigure(i, weight=1)

# 第二行按钮布局 - 运动控制按钮
row2_frame = tk.Frame(btn_frame)
row2_frame.pack(fill=tk.X, pady=5)

# 定义运动控制按钮
movement_commands = [
    ("开合", 0, "#2196F3"),       # mode=0
    ("俯仰", 2, "#2196F3"),       # mode=11
    ("偏摆", 11, "#2196F3"),      # mode=12
    ("夹钳1", 12, "#2196F3"),      # mode=13
    ("夹钳2", 13, "#2196F3"),      # mode=2
    ("旋转", 3, "#2196F3"),       # mode=3
]

# 距离输入框
distance_frame = tk.Frame(row2_frame)
distance_frame.grid(row=0, column=len(movement_commands), padx=(20, 0), sticky="e")  # 改为 grid

tk.Label(distance_frame, text="角度(deg):", fg="black", font=("Arial", 9)).grid(row=0, column=0, padx=2)

# 距离输入框变量
distance_var = tk.StringVar(value="10")

distance_entry = tk.Entry(
    distance_frame,
    textvariable=distance_var,
    width=8,
    font=("Arial", 9)
)
distance_entry.grid(row=0, column=1, padx=2)

cycle_var = tk.StringVar(value="0")
tk.Label(distance_frame, text="循环次数:", fg="black", font=("Arial", 9)).grid(row=0, column=2, padx=(8,2))
cycle_entry = tk.Entry(
    distance_frame,
    textvariable=cycle_var,
    width=6,
    font=("Arial", 9)
)
cycle_entry.grid(row=0, column=3, padx=2)

tk.Label(distance_frame, text="回差(deg):", fg="black", font=("Arial", 9)).grid(row=0, column=4, padx=(8,2))
backlash_var = tk.StringVar(value="0.0")
backlash_entry = tk.Entry(
    distance_frame,
    textvariable=backlash_var,
    width=6,
    font=("Arial", 9)
)
backlash_entry.grid(row=0, column=5, padx=2)

# 运动控制按钮
for i, (text, mode, color) in enumerate(movement_commands):
    btn = tk.Button(
        row2_frame,
        text=text,
        width=8,
        bg=color,
        fg="white",
        font=("Arial", 9, "bold"),
        command=lambda m=mode: send_movement_command(m)
    )
    btn.grid(row=0, column=i, padx=2, sticky="ew")
    all_buttons.append(btn)
    
    # 设置列权重
    row2_frame.columnconfigure(i, weight=1)

# 在距离输入框和运动控制按钮之间添加一些间距
distance_frame.grid(row=0, column=len(movement_commands), padx=(20, 0), sticky="e")
# 添加重连按钮到按钮列表
all_buttons.append(reconnect_button)

# 消息显示区域
msg_frame = tk.LabelFrame(main_frame, text="消息日志", padx=10, pady=10)
msg_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

# 创建滚动条
scrollbar = tk.Scrollbar(msg_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

# 创建文本显示框
message_text = tk.Text(
    msg_frame,
    height=12,
    yscrollcommand=scrollbar.set,
    wrap=tk.WORD,
    font=("Consolas", 9)
)
message_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scrollbar.config(command=message_text.yview)

# 添加清空按钮
clear_btn = tk.Button(
    msg_frame,
    text="清空日志",
    command=lambda: message_text.delete(1.0, tk.END),
    bg="#607D8B",
    fg="white"
)
clear_btn.pack(side=tk.BOTTOM, pady=(5, 0))

# 自定义指令区域
custom_frame = tk.LabelFrame(main_frame, text="自定义指令", padx=10, pady=10)
custom_frame.pack(fill=tk.X, pady=(0, 10))

# 输入框和发送按钮
input_frame = tk.Frame(custom_frame)
input_frame.pack(fill=tk.X, pady=5)

tk.Label(input_frame, text="指令:").pack(side=tk.LEFT, padx=(0, 5))

custom_command_entry = tk.Entry(input_frame, width=40)
custom_command_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
custom_command_entry.bind("<Return>", lambda e: send_custom_command())

send_btn = tk.Button(
    input_frame,
    text="发送",
    width=8,
    command=send_custom_command,
    bg="#2196F3",
    fg="white"
)
send_btn.pack(side=tk.RIGHT, padx=5)
all_buttons.append(send_btn)

common_commands = ["Stop","Start", "Clear", "UShow5D1", "Enable5D1", "Recover5D1"]
common_frame = tk.Frame(custom_frame)
common_frame.pack(fill=tk.X, pady=5)

tk.Label(common_frame, text="常用指令:", fg="black").pack(side=tk.LEFT, padx=(0, 5))

for cmd in common_commands:
    btn = tk.Button(
        common_frame,
        text=cmd,
        width=10,
        command=lambda c=cmd: send_command(c),
        fg="black"
    )
    btn.pack(side=tk.LEFT, padx=2)
    all_buttons.append(btn)

# 添加一个打开照片文件夹的按钮
# folder_frame = tk.Frame(main_frame)
# folder_frame.pack(fill=tk.X, pady=(5, 0))

# open_folder_btn = tk.Button(
#     folder_frame,
#     text="📁 打开照片文件夹",
#     command=lambda: os.startfile(PHOTOS_FOLDER) if os.path.exists(PHOTOS_FOLDER) 
#                     else messagebox.showinfo("提示", f"文件夹 {PHOTOS_FOLDER} 不存在"),
#     bg="#795548",
#     fg="black"
# )
# open_folder_btn.pack(side=tk.LEFT, padx=5)
# all_buttons.append(open_folder_btn)

# 状态栏
status_frame = tk.Frame(root, relief=tk.SUNKEN, bd=1)
status_frame.pack(side=tk.BOTTOM, fill=tk.X)

status_label = tk.Label(
    status_frame,
    text=f"当前连接: {current_host}:{current_port} | 错误端口: {current_error_port} | 照片文件夹: {PHOTOS_FOLDER} | 距离单位: mm",
    fg="black",
    bd=0,
    relief=tk.FLAT,
    anchor=tk.W
)
status_label.pack(side=tk.LEFT, padx=5)

time_label = tk.Label(
    status_frame,
    text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    bd=0,
    relief=tk.FLAT,
    anchor=tk.E
)
time_label.pack(side=tk.RIGHT, padx=5)

# 更新时间显示
def update_time():
    time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    root.after(1000, update_time)

# 更新状态指示灯
def update_status_light(connected):
    color = "#4CAF50" if connected else "#F44336"
    status_light.itemconfig(status_circle, fill=color)

# 程序启动消息
add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 程序启动")

# 检查并创建照片文件夹
if create_photos_folder():
    add_to_message_display(f"照片将保存到: {os.path.abspath(PHOTOS_FOLDER)}")

# 初始连接
def initial_connection():
    if connect_to_server():
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 初始连接成功")
        reconnect_button.config(text="✅ 已连接", bg="#4CAF50")
        # 连接成功后，等待一下再尝试连接错误端口
        root.after(1000, lambda: add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 错误端口连接中..."))
    else:
        add_to_message_display(f"[{datetime.now().strftime('%H:%M:%S')}] 初始连接失败")
        reconnect_button.config(text="🔁 重连", bg="#FF9800")
        update_connection_status(False)

# 延迟启动连接，确保UI已加载
root.after(100, initial_connection)
update_time()

# 启动主循环
root.mainloop()