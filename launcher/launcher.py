import customtkinter as ctk
from tkinter import messagebox, filedialog
import subprocess
import json
import os
import datetime
import sys
import threading

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

def get_script_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class ProgramLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("工具管理面板")
        self.root.geometry("1000x800")
        self.root.minsize(950, 650)

        self.script_dir = get_script_dir()
        self.programs = self.load_config()
        self.running_processes = {}
        self.log_file = os.path.join(self.script_dir, 'launcher.log')
        self._icon_images = []
        self.init_log_window = None

        self.setup_ui()
        # 异步检查缺失工具，不阻塞启动
        self.check_missing_tools_async()
        self.add_log("INFO", "工具箱已启动")

    def load_config(self):
        default_config = [
            {"name": "Xml管理工具", "path": "tool/XmlTool.exe", "desc": "批量处理xml参数", "icon": "📄"}
        ]
        try:
            config_path = os.path.join(self.script_dir, 'programs.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.add_log("ERROR", f"配置文件读取失败: {e}")
            messagebox.showerror("配置错误", f"配置文件失败: {e}")
        return default_config

    def setup_ui(self):
        self.main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)

        # 侧边栏
        self.sidebar = ctk.CTkFrame(self.main_container, width=240, corner_radius=0, fg_color="#f0f2f5")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(30, 20))
        ctk.CTkLabel(logo_frame, text="🛠️", font=("Segoe UI", 40)).pack()
        ctk.CTkLabel(logo_frame, text="工具箱", font=("Microsoft YaHei", 18, "bold"),
                     text_color="#4f46e5").pack()

        self.stats_label = ctk.CTkLabel(self.sidebar, text=f"📦 {len(self.programs)} 个工具",
                                        font=("Microsoft YaHei", 10), text_color="#6b7280")
        self.stats_label.pack(pady=20)

        nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", pady=20)
        for text, cmd in [("📋 全部工具", self.show_all_tools),
                          ("🔄 刷新列表", self.refresh_tools),
                          ("📊 运行日志", self.show_log)]:
            btn = ctk.CTkButton(nav_frame, text=text, fg_color="transparent",
                                text_color="#1f2937", hover_color="#e5e7eb",
                                anchor="w", command=cmd)
            btn.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(self.sidebar, text="Made with TC❤️", font=("Microsoft YaHei", 8),
                     text_color="#9ca3af").pack(side="bottom", pady=20)

        # 主区域
        self.main_area = ctk.CTkFrame(self.main_container, fg_color="#f8f9fa")
        self.main_area.pack(side="left", fill="both", expand=True)

        header = ctk.CTkFrame(self.main_area, fg_color="transparent", height=70)
        header.pack(fill="x", padx=20, pady=(15, 0))
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="工具管理中心", font=("Microsoft YaHei", 22, "bold"),
                     text_color="#1f2937").pack(side="left")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.on_search)
        self.search_entry = ctk.CTkEntry(header, textvariable=self.search_var,
                                         width=250, placeholder_text="🔍 搜索工具...")
        self.search_entry.pack(side="right")

        self.tools_container = ctk.CTkScrollableFrame(self.main_area, fg_color="#f8f9fa")
        self.tools_container.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        # 固定列数，只配置一次
        self.COLS = 3
        for i in range(self.COLS):
            self.tools_container.grid_columnconfigure(i, weight=1, uniform="tool_col")

        self.load_tools()

    def on_search(self, *args):
        self.load_tools(self.search_var.get())

    def show_all_tools(self):
        self.search_var.set("")
        self.load_tools()

    def load_tools(self, search_text=""):
        # 清空容器
        for widget in self.tools_container.winfo_children():
            widget.destroy()

        filtered = self.programs.copy()
        if search_text:
            filtered = [p for p in self.programs
                        if search_text.lower() in p['name'].lower()
                        or search_text.lower() in p.get('desc', '').lower()]

        if not filtered:
            ctk.CTkLabel(self.tools_container, text="😔 没有找到相关工具",
                         font=("Microsoft YaHei", 14), text_color="#6b7280").pack(pady=50)
            return

        for idx, prog in enumerate(filtered):
            row = idx // self.COLS
            col = idx % self.COLS
            self.create_tool_card(prog, row, col)

    def create_tool_card(self, prog, row, col):
        full_path = os.path.join(self.script_dir, prog['path'])
        exists = os.path.exists(full_path)
        icon = prog.get('icon', '🔧')

        card = ctk.CTkFrame(self.tools_container, corner_radius=10, border_width=1,
                            border_color="#e5e7eb", fg_color="white")
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        icon_label = ctk.CTkLabel(card, text=icon, font=("Segoe UI", 36), text_color="#4f46e5")
        icon_label.pack(pady=(15, 5))

        ctk.CTkLabel(card, text=prog['name'], font=("Microsoft YaHei", 12, "bold"),
                     text_color="#1f2937").pack()

        desc = prog.get('desc', '暂无描述')[:50]
        if len(prog.get('desc', '')) > 50:
            desc += "..."
        ctk.CTkLabel(card, text=desc, font=("Microsoft YaHei", 9),
                     text_color="#6b7280", wraplength=200, justify="center").pack(pady=(5, 10))

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))

        if exists:
            btn = ctk.CTkButton(btn_frame, text="🚀 启动", width=100,
                                fg_color="#4f46e5", hover_color="#6366f1",
                                command=lambda p=prog: self.run_program(p))
            btn.pack()
        else:
            ctk.CTkLabel(btn_frame, text="❌ 文件缺失", font=("Microsoft YaHei", 9),
                         text_color="#ef4444").pack()

    # 异步检查缺失工具
    def check_missing_tools_async(self):
        def _check():
            missing = [p['name'] for p in self.programs
                       if not os.path.exists(os.path.join(self.script_dir, p['path']))]
            if missing:
                self.root.after(0, lambda: self.show_notification(f"⚠️ 缺失 {len(missing)} 个工具文件", "warning"))
                self.add_log("WARNING", f"缺失: {', '.join(missing)}")
        threading.Thread(target=_check, daemon=True).start()

    # 优化日志写入：避免频繁打开关闭文件，使用缓冲写入（简单方案：追加时只开一次，但每次都要开；可改用队列）
    def add_log(self, level, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        try:
            # 使用追加模式，系统会缓存，性能尚可；如果追求极致可引入队列异步写入
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception:
            pass
        if self.init_log_window and self.init_log_window.winfo_exists():
            self.update_log_display()

    def get_log_content(self):
        if not os.path.exists(self.log_file):
            return "暂无日志记录"
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"读取失败: {e}"

    def clear_log(self):
        try:
            open(self.log_file, 'w', encoding='utf-8').close()
            self.add_log("INFO", "日志已清空")
            self.update_log_display()
            messagebox.showinfo("成功", "日志已清空")
        except Exception as e:
            messagebox.showerror("错误", f"清空失败: {e}")

    def update_log_display(self):
        if hasattr(self, 'log_textbox') and self.log_textbox.winfo_exists():
            content = self.get_log_content()
            self.log_textbox.delete("0.0", "end")
            self.log_textbox.insert("0.0", content)
            self.log_textbox.see("end")

    def show_log(self):
        if self.init_log_window and self.init_log_window.winfo_exists():
            self.init_log_window.lift()
            return

        self.init_log_window = ctk.CTkToplevel(self.root)
        self.init_log_window.title("运行日志")
        self.init_log_window.geometry("800x600")
        self.init_log_window.transient(self.root)

        control = ctk.CTkFrame(self.init_log_window, fg_color="transparent")
        control.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(control, text=f"📋 {self.log_file}", font=("Microsoft YaHei", 9),
                     text_color="#6b7280").pack(side="left")

        btn_frame = ctk.CTkFrame(control, fg_color="transparent")
        btn_frame.pack(side="right")
        for text, cmd, color in [("🔄 刷新", self.update_log_display, "#3b82f6"),
                                 ("🗑️ 清空", self.clear_log, "#ef4444"),
                                 ("💾 导出", self.export_log, "#10b981")]:
            btn = ctk.CTkButton(btn_frame, text=text, width=80, fg_color=color,
                                hover_color=color, command=cmd)
            btn.pack(side="left", padx=5)

        self.log_textbox = ctk.CTkTextbox(self.init_log_window, font=("Consolas", 10),
                                          wrap="word", fg_color="#1e1e1e", text_color="#00ff00")
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.update_log_display()

        self.init_log_window.protocol("WM_DELETE_WINDOW", self.on_log_close)
        self.start_auto_refresh()

    def start_auto_refresh(self):
        def refresh_loop():
            if self.init_log_window and self.init_log_window.winfo_exists():
                self.update_log_display()
                self.init_log_window.after(3000, refresh_loop)
        if self.init_log_window:
            self.init_log_window.after(3000, refresh_loop)

    def on_log_close(self):
        if self.init_log_window:
            self.init_log_window.destroy()
            self.init_log_window = None

    def export_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".log",
                                            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")])
        if path:
            try:
                import shutil
                shutil.copy2(self.log_file, path)
                messagebox.showinfo("成功", f"导出到 {path}")
                self.add_log("INFO", f"导出日志到 {path}")
            except Exception as e:
                messagebox.showerror("错误", str(e))

    def check_missing_tools(self):
        missing = [p['name'] for p in self.programs
                   if not os.path.exists(os.path.join(self.script_dir, p['path']))]
        if missing:
            self.show_notification(f"⚠️ 缺失 {len(missing)} 个工具文件", "warning")
            self.add_log("WARNING", f"缺失: {', '.join(missing)}")

    def show_notification(self, msg, typ="info"):
        color = "#f59e0b" if typ == "warning" else "#10b981"
        frame = ctk.CTkFrame(self.main_area, fg_color=color, height=40, corner_radius=8)
        frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(frame, text=msg, text_color="white", font=("Microsoft YaHei", 9)).pack(pady=5)
        self.root.after(3000, frame.destroy)

    def refresh_tools(self):
        self.programs = self.load_config()
        self.stats_label.configure(text=f"📦 {len(self.programs)} 个工具")
        self.load_tools(self.search_var.get())
        self.check_missing_tools()
        self.show_notification("刷新完成", "info")
        self.add_log("INFO", "刷新列表")

    def run_program(self, prog):
        exe_path = os.path.join(self.script_dir, prog['path'])
        try:
            self.show_notification(f"启动 {prog['name']}...", "info")
            self.add_log("INFO", f"启动 {prog['name']} ({exe_path})")

            # 优化启动速度：不使用 shell=True，直接执行
            # 如果 exe_path 包含空格，需要加引号，这里用 list 形式传递参数
            subprocess.Popen([exe_path], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
            # 如果目标程序需要特定工作目录，可以加 cwd 参数
        except Exception as e:
            self.add_log("ERROR", f"启动失败 {prog['name']}: {e}")
            messagebox.showerror("错误", f"启动失败:\n{e}")

if __name__ == "__main__":
    root = ctk.CTk()
    app = ProgramLauncher(root)
    root.mainloop()