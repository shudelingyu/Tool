import os
import re
import paramiko
import chardet
from paramiko import SFTPAttributes

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    import threading
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

STYLE_CONFIG = {
    "primary": "#2C3E50",
    "secondary": "#3498DB", 
    "success": "#27AE60",
    "danger": "#E74C3C",
    "warning": "#F39C12",
    "light": "#ECF0F1",
    "dark": "#34495E",
    "bg": "#F5F6FA",
    "accent": "#9B59B6"
}

style_done = False

def apply_modern_style():
    global style_done
    if style_done:
        return
    style_done = True
    
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except:
        pass
    
    style.configure("TFrame", background=STYLE_CONFIG["bg"])
    style.configure("TLabelframe", background=STYLE_CONFIG["bg"], foreground=STYLE_CONFIG["primary"], font=("Microsoft YaHei", 10, "bold"))
    style.configure("TLabelframe.Label", background=STYLE_CONFIG["bg"], foreground=STYLE_CONFIG["primary"])
    style.configure("TButton", font=("Microsoft YaHei", 9), padding=(15, 5))
    style.configure("TEntry", font=("Microsoft YaHei", 9))
    style.configure("TLabel", font=("Microsoft YaHei", 9), background=STYLE_CONFIG["bg"])
    style.configure("TRadiobutton", font=("Microsoft YaHei", 9), background=STYLE_CONFIG["bg"])
    style.configure("TCheckbutton", font=("Microsoft YaHei", 9))
    
    style.map("TButton",
        background=[("active", STYLE_CONFIG["secondary"]), ("pressed", STYLE_CONFIG["primary"])],
        foreground=[("active", "white"), ("pressed", "white")])
    
    style.configure("Treeview", font=("Microsoft YaHei", 9), rowheight=28)
    style.configure("Treeview.Heading", font=("Microsoft YaHei", 9, "bold"))


def find_parameter_in_xml(content, parameter_name):
    try:
        pattern = re.compile(
            r'<variable name="' + re.escape(parameter_name) + r'"[^>]*?>([^<]*)</variable>',
            re.MULTILINE | re.DOTALL
        )
        match = pattern.search(content)
        if match:
            return True, match.group(1).strip()
        return False, None
    except Exception:
        return False, None


def find_parameter_in_folder(folder_path, parameter_name, filename_filter=None):
    results = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'rb') as f:
                        raw_data = f.read()
                    detected = chardet.detect(raw_data)
                    encoding = detected.get('encoding', 'utf-8')
                    content = raw_data.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    for enc in ['gbk', 'gb2312', 'latin1']:
                        try:
                            content = raw_data.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        print(f"警告: 无法解码文件 {file_path}，跳过")
                        continue
                
                found, value = find_parameter_in_xml(content, parameter_name)
                if found:
                    results.append((file_path, value))
    return results


def delete_parameter_in_xml_content(content, parameter_name):
    """
    删除指定参数，如果该参数上方有紧邻的注释行（允许中间有空行），则一起删除。
    基于行扫描，保证只删除目标参数，不影响其他内容。
    返回 (是否成功, 新内容)
    """
    # 按行分割内容，保留换行符
    lines = content.splitlines(keepends=True)
    target_line_index = -1
    var_end_line_index = -1

    # 第一步：找到包含 <variable name="参数名"> 的行索引，以及包含 </variable> 的行索引（变量可能跨行）
    for i, line in enumerate(lines):
        if f'<variable name="{parameter_name}"' in line:
            target_line_index = i
            # 查找闭合标签所在的行
            for j in range(i, len(lines)):
                if '</variable>' in lines[j]:
                    var_end_line_index = j
                    break
            break

    if target_line_index == -1:
        return False, content

    # 第二步：向前查找，确定删除的起始行（包括注释行及其后的空行）
    start_line = target_line_index
    # 从目标行的上一行开始向前扫描
    for i in range(target_line_index - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            # 空行：继续向前，但保留空行？为了整洁，我们也删除注释和变量之间的空行
            continue
        if stripped.startswith('<!--') and stripped.endswith('-->'):
            # 找到注释行，将它作为起始行
            start_line = i
            # 继续向前检查是否有更多连续的注释/空行？通常只有一个注释，但如果有多个连续注释也一并删除
            continue
        # 遇到非空且非注释行，停止
        break

    # 第三步：删除从 start_line 到 var_end_line_index 的所有行
    new_lines = lines[:start_line] + lines[var_end_line_index + 1:]
    new_content = ''.join(new_lines)

    # 确认参数已被删除
    if f'name="{parameter_name}"' not in new_content:
        return True, new_content
    else:
        # 如果仍然存在，回退到原内容，避免误删
        return False, content


def delete_parameter_in_folder(folder_path, parameter_name, filename_filter=None):
    success_count = 0
    total_files = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                file_path = os.path.join(root, file)
                total_files += 1
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                success, new_content = delete_parameter_in_xml_content(content, parameter_name)
                if success:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    success_count += 1
    return success_count, total_files


def update_parameter_in_xml_content(content, parameter_name, new_value):
    pattern = re.compile(
        r'(<variable name="' + re.escape(parameter_name) + r'"[^>]*>)([^<]*)(</variable>)',
        re.MULTILINE | re.DOTALL
    )
    match = pattern.search(content)
    if match:
        new_content = pattern.sub(r'\1' + new_value + r'\3', content)
        return True, new_content
    return False, content


def update_parameter_in_folder(folder_path, parameter_name, new_value, filename_filter=None):
    success_count = 0
    total_files = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                file_path = os.path.join(root, file)
                total_files += 1
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                success, new_content = update_parameter_in_xml_content(content, parameter_name, new_value)
                if success:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    success_count += 1
    return success_count, total_files


def add_parameter_in_xml_content(content, parameter_name, value, comment=None):
    if f'name="{parameter_name}"' in content:
        return False, content
    
    last_variable_pos = content.rfind('</variable>')
    if last_variable_pos == -1:
        insert_pos = content.rfind('</MtmObject>')
        if insert_pos == -1:
            insert_pos = content.rfind('</PsmObject>')
        if insert_pos == -1:
            insert_pos = content.rfind('</ControllerObject>')
        if insert_pos == -1:
            insert_pos = content.rfind('</MotionObject>')
        if insert_pos == -1:
            return False, content
        
        new_param = '\n            '
        if comment:
            new_param += f'<!--{comment}-->\n            '
        new_param += f'<variable name="{parameter_name}">{value}</variable>'
        new_content = content[:insert_pos] + new_param + content[insert_pos:]
        return True, new_content
    else:
        insert_pos = last_variable_pos + len('</variable>')
        new_param = '\n            '
        if comment:
            new_param += f'<!--{comment}-->\n            '
        new_param += f'<variable name="{parameter_name}">{value}</variable>'
        new_content = content[:insert_pos] + new_param + content[insert_pos:]
        return True, new_content


def add_parameter_in_folder(folder_path, parameter_name, value, comment=None, filename_filter=None):
    success_count = 0
    total_files = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                file_path = os.path.join(root, file)
                total_files += 1
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                success, new_content = add_parameter_in_xml_content(content, parameter_name, value, comment)
                if success:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    success_count += 1
    return success_count, total_files


def list_parameters_in_xml(content):
    try:
        pattern = re.compile(
            r'<variable name="([^"]+)"[^>]*>([^<]*)</variable>',
            re.MULTILINE | re.DOTALL
        )
        params = []
        for match in pattern.finditer(content):
            params.append((match.group(1), match.group(2).strip()))
        return params
    except Exception:
        return []


def compare_xml_files(local_content, remote_content):
    local_params = {}
    for name, value in list_parameters_in_xml(local_content):
        local_params[name] = value
    
    remote_params = {}
    for name, value in list_parameters_in_xml(remote_content):
        remote_params[name] = value
    
    only_local = {}
    only_remote = {}
    different = {}
    
    for name, value in local_params.items():
        if name not in remote_params:
            only_local[name] = value
        elif remote_params[name] != value:
            different[name] = {'local': value, 'remote': remote_params[name]}
    
    for name, value in remote_params.items():
        if name not in local_params:
            only_remote[name] = value
    
    return only_local, only_remote, different


def collect_local_params(folder_path, filename_filter=None):
    all_params = {}
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                for name, value in list_parameters_in_xml(content):
                    if name not in all_params:
                        all_params[name] = set()
                    all_params[name].add(value)
    return all_params


class SSHClient:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client = None
        self.sftp = None
    
    def connect(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10
            )
            self.sftp = self.client.open_sftp()
            return True, "连接成功"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
    
    def disconnect(self):
        try:
            if self.sftp:
                self.sftp.close()
            if self.client:
                self.client.close()
            return True
        except Exception:
            return False
    
    def list_remote_files(self, remote_path, filename_filter=None):
        try:
            files = []
            for attr in self.sftp.listdir_attr(remote_path):
                full_path = remote_path + '/' + attr.filename
                if attr.filename.endswith('.xml') and (filename_filter is None or attr.filename == filename_filter):
                    files.append(full_path)
                elif attr.st_mode & 0o170000 == 0o040000:
                    files.extend(self.list_remote_files(full_path, filename_filter))
            return files
        except Exception:
            return []
    
    def list_remote_files_recursive(self, remote_path, filename_filter=None):
        files = []
        try:
            for attr in self.sftp.listdir_attr(remote_path):
                full_path = remote_path + '/' + attr.filename
                if attr.filename.endswith('.xml') and (filename_filter is None or attr.filename == filename_filter):
                    files.append(full_path)
                elif attr.st_mode & 0o170000 == 0o040000:
                    files.extend(self.list_remote_files_recursive(full_path, filename_filter))
        except Exception:
            pass
        return files
    
    def read_remote_file(self, remote_path):
        try:
            with self.sftp.file(remote_path, 'r') as f:
                return f.read().decode('utf-8')
        except Exception:
            return None
    
    def write_remote_file(self, remote_path, content):
        try:
            with self.sftp.file(remote_path, 'w') as f:
                f.write(content)
            return True
        except Exception:
            return False
    
    def delete_remote_file(self, remote_path, parameter_name):
        content = self.read_remote_file(remote_path)
        if content is None:
            return False
        success, new_content = delete_parameter_in_xml_content(content, parameter_name)
        if success:
            return self.write_remote_file(remote_path, new_content)
        return False
    
    def update_remote_file(self, remote_path, parameter_name, new_value):
        content = self.read_remote_file(remote_path)
        if content is None:
            return False
        success, new_content = update_parameter_in_xml_content(content, parameter_name, new_value)
        if success:
            return self.write_remote_file(remote_path, new_content)
        return False
    
    def add_remote_file(self, remote_path, parameter_name, value, comment=None):
        content = self.read_remote_file(remote_path)
        if content is None:
            return False
        success, new_content = add_parameter_in_xml_content(content, parameter_name, value, comment)
        if success:
            return self.write_remote_file(remote_path, new_content)
        return False
    
    def find_remote(self, remote_path, parameter_name, filename_filter=None):
        results = []
        files = self.list_remote_files(remote_path, filename_filter)
        for file_path in files:
            content = self.read_remote_file(file_path)
            if content:
                found, value = find_parameter_in_xml(content, parameter_name)
                if found:
                    results.append((file_path, value))
        return results
    
    def list_remote_all(self, remote_path, filename_filter=None):
        all_params = {}
        files = self.list_remote_files(remote_path, filename_filter)
        for file_path in files:
            content = self.read_remote_file(file_path)
            if content:
                for name, value in list_parameters_in_xml(content):
                    if name not in all_params:
                        all_params[name] = set()
                    all_params[name].add(value)
        return all_params
    
    def delete_remote_folder(self, remote_path, parameter_name, filename_filter=None):
        success_count = 0
        total_files = 0
        files = self.list_remote_files(remote_path, filename_filter)
        for file_path in files:
            total_files += 1
            if self.delete_remote_file(file_path, parameter_name):
                success_count += 1
        return success_count, total_files
    
    def update_remote_folder(self, remote_path, parameter_name, new_value, filename_filter=None):
        success_count = 0
        total_files = 0
        files = self.list_remote_files(remote_path, filename_filter)
        for file_path in files:
            total_files += 1
            if self.update_remote_file(file_path, parameter_name, new_value):
                success_count += 1
        return success_count, total_files
    
    def add_remote_folder(self, remote_path, parameter_name, value, comment=None, filename_filter=None):
        success_count = 0
        total_files = 0
        files = self.list_remote_files(remote_path, filename_filter)
        for file_path in files:
            total_files += 1
            if self.add_remote_file(file_path, parameter_name, value, comment):
                success_count += 1
        return success_count, total_files
    
    def compare_with_local(self, remote_path, local_path, filename_filter=None):
        results = []
        remote_files = self.list_remote_files_recursive(remote_path, filename_filter)
        remote_files_dict = {os.path.basename(f): f for f in remote_files}
        local_files_dict = {}
        
        for root, dirs, files in os.walk(local_path):
            for file in files:
                if file.endswith('.xml') and (filename_filter is None or file == filename_filter):
                    local_files_dict[file] = os.path.join(root, file)
        
        for remote_file, remote_full_path in remote_files_dict.items():
            local_file_path = local_files_dict.get(remote_file)
            remote_content = self.read_remote_file(remote_full_path)
            if remote_content is None:
                continue
            
            if local_file_path:
                with open(local_file_path, 'r', encoding='utf-8') as f:
                    local_content = f.read()
                only_local, only_remote, different = compare_xml_files(local_content, remote_content)
            else:
                only_local = {}
                only_remote = {}
                for name, value in list_parameters_in_xml(remote_content):
                    only_remote[name] = value
                different = {}
            
            if only_local or only_remote or different:
                results.append({
                    'file': remote_file,
                    'only_local': only_local,
                    'only_remote': only_remote,
                    'different': different
                })
        
        for local_file, local_full_path in local_files_dict.items():
            if local_file not in remote_files_dict:
                with open(local_full_path, 'r', encoding='utf-8') as f:
                    local_content = f.read()
                only_local = {}
                only_remote = {}
                for name, value in list_parameters_in_xml(local_content):
                    only_local[name] = value
                different = {}
                results.append({
                    'file': local_file,
                    'only_local': only_local,
                    'only_remote': only_remote,
                    'different': different
                })
        
        return results


if GUI_AVAILABLE:
    class XMLParameterTool:
        def __init__(self, root):
            self.root = root
            self.root.title("XML参数管理工具")
            self.root.geometry("1000x700")
            self.root.minsize(800, 550)
            self.root.configure(bg=STYLE_CONFIG["bg"])
            self.root.option_add("*TFrame*background", STYLE_CONFIG["bg"])
            self.root.option_add("*TLabel*background", STYLE_CONFIG["bg"])
            
            apply_modern_style()
            
            self.folder_path = tk.StringVar()
            self.file_path = tk.StringVar()
            self.ssh_client = None
            self.remote_mode = tk.BooleanVar(value=False)
            self.single_file_mode = tk.BooleanVar(value=False)
            self.use_filename_filter = tk.BooleanVar(value=False)
            self.filename_filter = tk.StringVar()
            self.setup_ui()
        
        def setup_ui(self):
            header_frame = tk.Frame(self.root, bg=STYLE_CONFIG["primary"], height=50)
            header_frame.pack(fill=tk.X)
            header_frame.pack_propagate(False)
            
            tk.Label(header_frame, text="XML参数管理工具", font=("Microsoft YaHei", 16, "bold"),
                   bg=STYLE_CONFIG["primary"], fg="white").pack(side=tk.LEFT, padx=20, pady=10)
            
            mode_frame = tk.Frame(self.root, bg=STYLE_CONFIG["light"], padx=20, pady=10)
            mode_frame.pack(fill=tk.X)
            
            tk.Label(mode_frame, text="模式:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["light"]).pack(side=tk.LEFT, padx=(0, 10))
            rb_local = ttk.Radiobutton(mode_frame, text="本地模式", variable=self.remote_mode, value=False, command=self.on_mode_change)
            rb_local.pack(side=tk.LEFT, padx=5)
            rb_remote = ttk.Radiobutton(mode_frame, text="远程模式(SSH)", variable=self.remote_mode, value=True, command=self.on_mode_change)
            rb_remote.pack(side=tk.LEFT, padx=5)
            
            tk.Label(mode_frame, text="范围:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["light"]).pack(side=tk.LEFT, padx=(20, 0))
            rb_batch = ttk.Radiobutton(mode_frame, text="批量(目录)", variable=self.single_file_mode, value=False, command=self.update_path_label)
            rb_batch.pack(side=tk.LEFT, padx=5)
            rb_single = ttk.Radiobutton(mode_frame, text="单个(XML)", variable=self.single_file_mode, value=True, command=self.update_path_label)
            rb_single.pack(side=tk.LEFT, padx=5)
            
            self.local_frame = ttk.Frame(self.root)
            self.local_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            path_frame = tk.Frame(self.local_frame, bg=STYLE_CONFIG["bg"])
            path_frame.pack(fill=tk.X, pady=(0, 10))
            
            tk.Label(path_frame, text="工作目录:", font=("Microsoft YaHei", 10, "bold"), 
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(side=tk.LEFT)
            self.path_label = tk.Label(path_frame, font=("Microsoft YaHei", 10, "bold"), 
                                       bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"])
            self.path_label.pack(side=tk.LEFT)
            path_entry = tk.Entry(path_frame, textvariable=self.folder_path, width=60, font=("Microsoft YaHei", 9))
            path_entry.pack(side=tk.LEFT, padx=10)
            ttk.Button(path_frame, text="浏览", command=self.browse_folder).pack(side=tk.LEFT)
            
            # 添加文件名过滤控件
            self.filter_frame = tk.Frame(self.local_frame, bg=STYLE_CONFIG["bg"])
            self.filter_frame.pack(fill=tk.X, pady=(0, 10))
            tk.Checkbutton(self.filter_frame, text="仅处理特定文件名", variable=self.use_filename_filter,
                          bg=STYLE_CONFIG["bg"], font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
            self.filter_entry = ttk.Entry(self.filter_frame, width=25, font=("Microsoft YaHei", 9))
            self.filter_entry.pack(side=tk.LEFT, padx=10)
            self.filter_entry.bind("<FocusOut>", lambda e: self.filename_filter.set(self.filter_entry.get().strip()))
            self.filter_entry.bind("<KeyRelease>", lambda e: self.filename_filter.set(self.filter_entry.get().strip()))
            self.update_filter_visibility()
            
            self.notebook = ttk.Notebook(self.local_frame, padding=5)
            self.notebook.pack(fill=tk.BOTH, expand=True)
            
            self.tab_find = ttk.Frame(self.notebook)
            self.tab_delete = ttk.Frame(self.notebook)
            self.tab_update = ttk.Frame(self.notebook)
            self.tab_add = ttk.Frame(self.notebook)
            self.tab_list = ttk.Frame(self.notebook)
            self.tab_compare = ttk.Frame(self.notebook)
            
            self.notebook.add(self.tab_find, text="查找参数")
            self.notebook.add(self.tab_delete, text="删除参数")
            self.notebook.add(self.tab_update, text="修改参数")
            self.notebook.add(self.tab_add, text="添加参数")
            self.notebook.add(self.tab_list, text="参数列表")
            self.notebook.add(self.tab_compare, text="文件对比")
            
            style = ttk.Style()
            style.configure("TNotebook", background=STYLE_CONFIG["bg"])
            style.configure("TNotebook.TFrame", background=STYLE_CONFIG["bg"])
            style.configure("TFrame", background=STYLE_CONFIG["bg"])
            
            self.setup_tab_find()
            self.setup_tab_delete()
            self.setup_tab_update()
            self.setup_tab_add()
            self.setup_tab_list()
            self.setup_tab_compare()
            
            status_frame = tk.Frame(self.root, bg=STYLE_CONFIG["primary"], height=30)
            status_frame.pack(fill=tk.X, side=tk.BOTTOM)
            status_frame.pack_propagate(False)
            self.status_label = tk.Label(status_frame, text="就绪", font=("Microsoft YaHei", 9), 
                                      bg=STYLE_CONFIG["primary"], fg="white")
            self.status_label.pack(side=tk.LEFT, padx=20)
        
        def update_filter_visibility(self):
            if self.single_file_mode.get():
                self.filter_frame.pack_forget()
            else:
                self.filter_frame.pack(fill=tk.X, pady=(0, 10))
        
        def get_filename_filter(self):
            if self.single_file_mode.get():
                return None
            if self.use_filename_filter.get():
                name = self.filename_filter.get().strip()
                return name if name else None
            return None
        
        def setup_ssh_ui(self):
            self.remote_frame = tk.Frame(self.root, bg=STYLE_CONFIG["light"], padx=20, pady=15)
            self.remote_frame.pack(fill=tk.X, before=self.local_frame)
            
            tk.Label(self.remote_frame, text="SSH连接", font=("Microsoft YaHei", 11, "bold"),
                   bg=STYLE_CONFIG["light"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 10))
            
            form_frame = tk.Frame(self.remote_frame, bg=STYLE_CONFIG["light"])
            form_frame.pack(fill=tk.X)
            
            tk.Label(form_frame, text="主机:", font=("Microsoft YaHei", 9), bg=STYLE_CONFIG["light"]).grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
            self.ssh_host = ttk.Entry(form_frame, width=20, font=("Microsoft YaHei", 9))
            self.ssh_host.grid(row=0, column=1, sticky=tk.W, padx=5)
            
            tk.Label(form_frame, text="端口:", font=("Microsoft YaHei", 9), bg=STYLE_CONFIG["light"]).grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
            self.ssh_port = ttk.Entry(form_frame, width=8, font=("Microsoft YaHei", 9))
            self.ssh_port.grid(row=0, column=3, sticky=tk.W, padx=5)
            self.ssh_port.insert(0, "22")
            
            tk.Label(form_frame, text="用户名:", font=("Microsoft YaHei", 9), bg=STYLE_CONFIG["light"]).grid(row=0, column=4, sticky=tk.W, padx=(20, 5))
            self.ssh_user = ttk.Entry(form_frame, width=15, font=("Microsoft YaHei", 9))
            self.ssh_user.grid(row=0, column=5, sticky=tk.W, padx=5)
            
            tk.Label(form_frame, text="密码:", font=("Microsoft YaHei", 9), bg=STYLE_CONFIG["light"]).grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
            self.ssh_pass = ttk.Entry(form_frame, width=20, show="*", font=("Microsoft YaHei", 9))
            self.ssh_pass.grid(row=1, column=1, sticky=tk.W, pady=(10, 0))
            
            btn_frame = tk.Frame(form_frame, bg=STYLE_CONFIG["light"])
            btn_frame.grid(row=1, column=2, columnspan=4, sticky=tk.W, pady=(10, 0))
            
            style = ttk.Style()
            style.configure("Connect.TButton", font=("Microsoft YaHei", 9))
            
            ttk.Button(btn_frame, text="连接", command=self.do_connect, style="Connect.TButton").pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="断开", command=self.do_disconnect).pack(side=tk.LEFT, padx=5)
            
            self.ssh_status = tk.Label(btn_frame, text="未连接", font=("Microsoft YaHei", 9), 
                                   bg=STYLE_CONFIG["light"], fg=STYLE_CONFIG["danger"])
            self.ssh_status.pack(side=tk.LEFT, padx=20)
        
        def on_mode_change(self):
            if self.remote_mode.get():
                self.setup_ssh_ui()
            elif hasattr(self, 'remote_frame'):
                self.remote_frame.pack_forget()
            self.update_path_label()
        
        def update_path_label(self):
            if self.single_file_mode.get():
                self.path_label.config(text="文件路径:")
            else:
                self.path_label.config(text="工作目录:")
            self.update_filter_visibility()
        
        def do_connect(self):
            host = self.ssh_host.get().strip()
            port = int(self.ssh_port.get().strip() or 22)
            user = self.ssh_user.get().strip()
            password = self.ssh_pass.get()
            
            if not host or not user or not password:
                messagebox.showwarning("警告", "请填写所有连接信息")
                return
            
            self.status_label.config(text="正在连接...")
            def run():
                self.ssh_client = SSHClient(host, port, user, password)
                success, msg = self.ssh_client.connect()
                self.root.after(0, lambda: self.on_connect_result(success, msg))
            
            threading.Thread(target=run, daemon=True).start()
        
        def on_connect_result(self, success, msg):
            if success:
                self.ssh_status.config(text="已连接", fg=STYLE_CONFIG["success"])
                self.status_label.config(text=f"已连接到 {self.ssh_host.get()}")
            else:
                self.ssh_status.config(text="连接失败", fg=STYLE_CONFIG["danger"])
                self.status_label.config(text="连接失败")
                messagebox.showerror("错误", msg)
        
        def do_disconnect(self):
            if self.ssh_client:
                self.ssh_client.disconnect()
                self.ssh_client = None
            self.ssh_status.config(text="未连接", fg=STYLE_CONFIG["danger"])
            self.status_label.config(text="已断开连接")
        
        def create_tab_content(self, parent, title, has_input=True):
            container = tk.Frame(parent, bg=STYLE_CONFIG["bg"])
            container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
            return container
        
        def setup_tab_find(self):
            container = self.create_tab_content(self.tab_find, "查找参数")
            
            input_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            input_frame.pack(fill=tk.X, pady=(0, 15))
            
            tk.Label(input_frame, text="参数名:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_find_name = ttk.Entry(input_frame, width=30, font=("Microsoft YaHei", 9))
            self.entry_find_name.pack(side=tk.LEFT, padx=10)
            
            btn = ttk.Button(input_frame, text="查找", command=self.do_find)
            btn.pack(side=tk.LEFT)
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="查找结果:", font=("Microsoft YaHei", 10, "bold"), 
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            self.text_find_result = scrolledtext.ScrolledText(result_frame, width=90, height=25, font=("Consolas", 9),
                                                      bg="white", fg=STYLE_CONFIG["dark"])
            self.text_find_result.pack(fill=tk.BOTH, expand=True)
        
        def setup_tab_delete(self):
            container = self.create_tab_content(self.tab_delete, "删除参数")
            
            input_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            input_frame.pack(fill=tk.X, pady=(0, 15))
            
            tk.Label(input_frame, text="参数名:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_delete_name = ttk.Entry(input_frame, width=30, font=("Microsoft YaHei", 9))
            self.entry_delete_name.pack(side=tk.LEFT, padx=10)
            
            btn = ttk.Button(input_frame, text="删除", command=self.do_delete)
            btn.pack(side=tk.LEFT)
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="操作结果:", font=("Microsoft YaHei", 10, "bold"),
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            self.text_delete_result = scrolledtext.ScrolledText(result_frame, width=90, height=25, font=("Consolas", 9),
                                                      bg="white", fg=STYLE_CONFIG["dark"])
            self.text_delete_result.pack(fill=tk.BOTH, expand=True)
        
        def setup_tab_update(self):
            container = self.create_tab_content(self.tab_update, "修改参数")
            
            input_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            input_frame.pack(fill=tk.X, pady=(0, 15))
            
            row1 = tk.Frame(input_frame, bg=STYLE_CONFIG["bg"])
            row1.pack(fill=tk.X)
            tk.Label(row1, text="参数名:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_update_name = ttk.Entry(row1, width=30, font=("Microsoft YaHei", 9))
            self.entry_update_name.pack(side=tk.LEFT, padx=10)
            
            row2 = tk.Frame(input_frame, bg=STYLE_CONFIG["bg"])
            row2.pack(fill=tk.X, pady=5)
            tk.Label(row2, text="新    值:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_update_value = ttk.Entry(row2, width=30, font=("Microsoft YaHei", 9))
            self.entry_update_value.pack(side=tk.LEFT, padx=10)
            
            btn = ttk.Button(row2, text="修改", command=self.do_update)
            btn.pack(side=tk.LEFT)
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="操作结果:", font=("Microsoft YaHei", 10, "bold"),
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            self.text_update_result = scrolledtext.ScrolledText(result_frame, width=90, height=22, font=("Consolas", 9),
                                                              bg="white", fg=STYLE_CONFIG["dark"])
            self.text_update_result.pack(fill=tk.BOTH, expand=True)
        
        def setup_tab_add(self):
            container = self.create_tab_content(self.tab_add, "添加参数")
            
            input_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            input_frame.pack(fill=tk.X, pady=(0, 15))
            
            row1 = tk.Frame(input_frame, bg=STYLE_CONFIG["bg"])
            row1.pack(fill=tk.X)
            tk.Label(row1, text="参数名:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_add_name = ttk.Entry(row1, width=30, font=("Microsoft YaHei", 9))
            self.entry_add_name.pack(side=tk.LEFT, padx=10)
            
            row2 = tk.Frame(input_frame, bg=STYLE_CONFIG["bg"])
            row2.pack(fill=tk.X, pady=5)
            tk.Label(row2, text="参数值:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_add_value = ttk.Entry(row2, width=30, font=("Microsoft YaHei", 9))
            self.entry_add_value.pack(side=tk.LEFT, padx=10)
            
            row3 = tk.Frame(input_frame, bg=STYLE_CONFIG["bg"])
            row3.pack(fill=tk.X, pady=5)
            tk.Label(row3, text="注释:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_add_comment = ttk.Entry(row3, width=30, font=("Microsoft YaHei", 9))
            self.entry_add_comment.pack(side=tk.LEFT, padx=10)
            
            btn = ttk.Button(row3, text="添加", command=self.do_add)
            btn.pack(side=tk.LEFT)
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="操作结果:", font=("Microsoft YaHei", 10, "bold"),
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            self.text_add_result = scrolledtext.ScrolledText(result_frame, width=90, height=18, font=("Consolas", 9),
                                                      bg="white", fg=STYLE_CONFIG["dark"])
            self.text_add_result.pack(fill=tk.BOTH, expand=True)
        
        def setup_tab_list(self):
            container = self.create_tab_content(self.tab_list, "参数列表")
            
            btn_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            btn_frame.pack(fill=tk.X, pady=(0, 10))
            btn = ttk.Button(btn_frame, text="列出所有参数", command=self.do_list)
            btn.pack()
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="参数列表:", font=("Microsoft YaHei", 10, "bold"),
                   bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            self.text_list_result = scrolledtext.ScrolledText(result_frame, width=90, height=28, font=("Consolas", 9),
                                                  bg="white", fg=STYLE_CONFIG["dark"])
            self.text_list_result.pack(fill=tk.BOTH, expand=True)
        
        def setup_tab_compare(self):
            container = self.create_tab_content(self.tab_compare, "远程与本地对比")
            
            path_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            path_frame.pack(fill=tk.X, pady=(0, 15))
            
            row1 = tk.Frame(path_frame, bg=STYLE_CONFIG["bg"])
            row1.pack(fill=tk.X)
            tk.Label(row1, text="本地目录:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_local_path = ttk.Entry(row1, width=40, font=("Microsoft YaHei", 9))
            self.entry_local_path.pack(side=tk.LEFT, padx=10)
            ttk.Button(row1, text="浏览", command=self.browse_local_folder).pack(side=tk.LEFT)
            
            row2 = tk.Frame(path_frame, bg=STYLE_CONFIG["bg"])
            row2.pack(fill=tk.X, pady=5)
            tk.Label(row2, text="远程目录:", font=("Microsoft YaHei", 10), bg=STYLE_CONFIG["bg"]).pack(side=tk.LEFT)
            self.entry_remote_path = ttk.Entry(row2, width=40, font=("Microsoft YaHei", 9))
            self.entry_remote_path.pack(side=tk.LEFT, padx=10)
            ttk.Button(row2, text="浏览", command=self.compare_browse_folder).pack(side=tk.LEFT)
            
            btn_frame = tk.Frame(path_frame, bg=STYLE_CONFIG["bg"])
            btn_frame.pack(pady=10)
            self.btn_compare = ttk.Button(btn_frame, text="开始对比", command=self.do_compare)
            self.btn_compare.pack(side=tk.LEFT, padx=5)
            self.btn_sync = ttk.Button(btn_frame, text="刷新", command=self.do_compare)
            self.btn_sync.pack(side=tk.LEFT, padx=5)
            
            result_frame = tk.Frame(container, bg=STYLE_CONFIG["bg"])
            result_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(result_frame, text="对比结果:", font=("Microsoft YaHei", 10, "bold"),
                bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W, pady=(0, 5))
            
            compare_frame = tk.Frame(result_frame)
            compare_frame.pack(fill=tk.BOTH, expand=True)
            
            local_frame = tk.Frame(compare_frame, bg=STYLE_CONFIG["bg"])
            local_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
            
            tk.Label(local_frame, text="本地参数", font=("Microsoft YaHei", 10, "bold"),
                bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W)
            
            local_tree_frame = tk.Frame(local_frame)
            local_tree_frame.pack(fill=tk.BOTH, expand=True)
            
            self.local_tree = ttk.Treeview(local_tree_frame, height=15, selectmode="browse")
            self.local_tree["columns"] = ("value", "status")
            self.local_tree.column("#0", width=150, minwidth=100)
            self.local_tree.column("value", width=150, minwidth=100)
            self.local_tree.column("status", width=80, minwidth=60)
            
            self.local_tree.heading("#0", text="参数名")
            self.local_tree.heading("value", text="值")
            self.local_tree.heading("status", text="状态")
            
            local_vsb = ttk.Scrollbar(local_tree_frame, orient="vertical", command=self.local_tree.yview)
            self.local_tree.configure(yscrollcommand=local_vsb.set)
            
            self.local_tree.grid(row=0, column=0, sticky="nsew")
            local_vsb.grid(row=0, column=1, sticky="ns")
            local_tree_frame.grid_rowconfigure(0, weight=1)
            local_tree_frame.grid_columnconfigure(0, weight=1)
            
            arrow_frame = tk.Frame(compare_frame, bg=STYLE_CONFIG["bg"], width=100)
            arrow_frame.pack(side=tk.LEFT, fill=tk.Y)
            arrow_frame.pack_propagate(False)
            
            ttk.Button(arrow_frame, text="→", command=self.sync_selected_to_remote).pack(pady=(70, 10))
            ttk.Button(arrow_frame, text="←", command=self.sync_selected_to_local).pack(pady=(30, 10))
            
            remote_frame = tk.Frame(compare_frame, bg=STYLE_CONFIG["bg"])
            remote_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
            
            tk.Label(remote_frame, text="远端参数", font=("Microsoft YaHei", 10, "bold"),
                bg=STYLE_CONFIG["bg"], fg=STYLE_CONFIG["primary"]).pack(anchor=tk.W)
            
            remote_tree_frame = tk.Frame(remote_frame)
            remote_tree_frame.pack(fill=tk.BOTH, expand=True)
            
            self.remote_tree = ttk.Treeview(remote_tree_frame, height=15, selectmode="browse")
            self.remote_tree["columns"] = ("value", "status")
            self.remote_tree.column("#0", width=150, minwidth=100)
            self.remote_tree.column("value", width=150, minwidth=100)
            self.remote_tree.column("status", width=80, minwidth=60)
            
            self.remote_tree.heading("#0", text="参数名")
            self.remote_tree.heading("value", text="值")
            self.remote_tree.heading("status", text="状态")
            
            remote_vsb = ttk.Scrollbar(remote_tree_frame, orient="vertical", command=self.remote_tree.yview)
            self.remote_tree.configure(yscrollcommand=remote_vsb.set)
            
            self.remote_tree.grid(row=0, column=0, sticky="nsew")
            remote_vsb.grid(row=0, column=1, sticky="ns")
            remote_tree_frame.grid_rowconfigure(0, weight=1)
            remote_tree_frame.grid_columnconfigure(0, weight=1)
            
            self.local_tree.bind("<Button-3>", self.on_local_right_click)
            self.remote_tree.bind("<Button-3>", self.on_remote_right_click)
            
            self.compare_results = []
            self.current_local_path = ""
            self.current_remote_path = ""
        
        def compare_browse_folder(self):
            if not self.ssh_client or not self.ssh_client.sftp:
                messagebox.showwarning("警告", "请先连接SSH服务器")
                return
            
            dialog = tk.Toplevel(self.root)
            dialog.title("选择对比用的远程目录")
            dialog.geometry("600x600")
            
            ttk.Label(dialog, text="路径:").pack(pady=(10,0))
            entry = ttk.Entry(dialog, width=60)
            entry.pack(pady=5)
            entry.insert(0, self.entry_remote_path.get() or "/")
            
            tv = ttk.Treeview(dialog, height=12)
            tv.heading("#0", text="名称")
            tv.column("#0", width=350)
            tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            def refresh_tree(path):
                tv.delete(*tv.get_children())
                try:
                    if path != "/":
                        tv.insert("", "end", text="..", values=("返回上级",))
                    for attr in self.ssh_client.sftp.listdir_attr(path):
                        if attr.st_mode & 0o170000 == 0o040000:
                            tv.insert("", "end", text=attr.filename, values=("文件夹",))
                        elif attr.filename.endswith('.xml'):
                            tv.insert("", "end", text=attr.filename, values=("文件",))
                except Exception:
                    pass
            
            def on_dbl_click(event):
                item = tv.identify_row(event.y)
                if item:
                    name = tv.item(item, "text")
                    if name == "..":
                        current_path = entry.get().rstrip("/")
                        parent_path = "/".join(current_path.split("/")[:-1]) or "/"
                        entry.delete(0, tk.END)
                        entry.insert(0, parent_path)
                        refresh_tree(parent_path)
                    else:
                        new_path = entry.get().rstrip("/") + "/" + name
                        entry.delete(0, tk.END)
                        entry.insert(0, new_path)
                        refresh_tree(new_path)
            
            tv.bind("<Double-1>", on_dbl_click)
            refresh_tree(entry.get())
            
            def on_ok():
                path = entry.get().rstrip("/")
                self.entry_remote_path.delete(0, tk.END)
                self.entry_remote_path.insert(0, path)
                dialog.destroy()
            
            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT)
        
        def browse_local_folder(self):
            folder = filedialog.askdirectory(title="选择本地XML文件夹")
            if folder:
                self.entry_local_path.delete(0, tk.END)
                self.entry_local_path.insert(0, folder)
        
        def do_compare(self):
            local_path = self.entry_local_path.get().strip()
            remote_path = self.entry_remote_path.get().strip()
            
            if not local_path:
                messagebox.showwarning("警告", "请选择本地目录")
                return
            if not remote_path:
                messagebox.showwarning("警告", "请输入远程目录")
                return
            if not self.ssh_client or not self.ssh_client.sftp:
                messagebox.showwarning("警告", "请先连接SSH服务器")
                return
            
            if not os.path.exists(local_path):
                messagebox.showwarning("警告", "本地目录不存在")
                return
            
            self.status_label.config(text="正在对比...")
            self.current_local_path = local_path
            self.current_remote_path = remote_path
            
            for item in self.local_tree.get_children():
                self.local_tree.delete(item)
            for item in self.remote_tree.get_children():
                self.remote_tree.delete(item)
            
            filename_filter = self.get_filename_filter()
            
            def run():
                results = self.ssh_client.compare_with_local(remote_path, local_path, filename_filter)
                self.root.after(0, lambda: self.show_compare_results(results, local_path, remote_path))
            
            threading.Thread(target=run, daemon=True).start()

        def show_compare_results(self, results, local_path, remote_path):
            self.compare_results = results
            self.current_local_path = local_path
            self.current_remote_path = remote_path
            
            for item in self.local_tree.get_children():
                self.local_tree.delete(item)
            for item in self.remote_tree.get_children():
                self.remote_tree.delete(item)
            
            if not results:
                self.status_label.config(text="对比完成: 无差异")
                messagebox.showinfo("提示", "所有文件参数一致")
                return
            
            for item in results:
                file_name = item['file']
                only_local = item['only_local']
                only_remote = item['only_remote']
                different = item['different']
                
                local_parent = self.local_tree.insert("", "end", text=f"【{file_name}】", 
                                                    values=("", ""), open=True)
                for name in sorted(only_local.keys()):
                    self.local_tree.insert(local_parent, "end", text=name, 
                                        values=(only_local[name], "独有"))
                for name in sorted(different.keys()):
                    self.local_tree.insert(local_parent, "end", text=name, 
                                        values=(different[name]['local'], "不同"))
                
                remote_parent = self.remote_tree.insert("", "end", text=f"【{file_name}】", 
                                                        values=("", ""), open=True)
                for name in sorted(only_remote.keys()):
                    self.remote_tree.insert(remote_parent, "end", text=name, 
                                        values=(only_remote[name], "独有"))
                for name in sorted(different.keys()):
                    self.remote_tree.insert(remote_parent, "end", text=name, 
                                        values=(different[name]['remote'], "不同"))
            
            self.status_label.config(text=f"对比完成: {len(results)} 个文件有差异")
        
        def on_compare_item_click(self, event):
            # 保留原方法，但实际使用了新的左右树同步，此方法已不被调用，但保留以防万一
            pass
        
        def sync_selected_to_remote(self):
            selected = self.local_tree.selection()
            if not selected:
                messagebox.showwarning("警告", "请先选择本地参数")
                return
            
            item = self.local_tree.item(selected[0])
            param_name = item['text']
            values = item['values']
            
            if not values or len(values) < 2:
                return
            
            param_value = values[0]
            status = values[1]
            
            parent = self.local_tree.parent(selected[0])
            if parent:
                file_name = self.local_tree.item(parent)['text'].strip('【】')
            else:
                return
            
            try:
                if status == "独有":
                    if messagebox.askyesno("确认", f"将独有参数 [{param_name}] 添加到远端?"):
                        self.add_param_to_remote(file_name, param_name, param_value)
                elif status == "不同":
                    if messagebox.askyesno("确认", f"将本地参数 [{param_name}] 覆盖远端?"):
                        self.update_param_to_remote(file_name, param_name, param_value)
            except Exception as e:
                messagebox.showerror("错误", f"同步失败: {str(e)}")

        def sync_selected_to_local(self):
            selected = self.remote_tree.selection()
            if not selected:
                messagebox.showwarning("警告", "请先选择远端参数")
                return
            
            item = self.remote_tree.item(selected[0])
            param_name = item['text']
            values = item['values']
            
            if not values or len(values) < 2:
                return
            
            param_value = values[0]
            status = values[1]
            
            parent = self.remote_tree.parent(selected[0])
            if parent:
                file_name = self.remote_tree.item(parent)['text'].strip('【】')
            else:
                return
            
            try:
                if status == "独有":
                    if messagebox.askyesno("确认", f"将独有参数 [{param_name}] 添加到本地?"):
                        self.add_param_to_local(file_name, param_name, param_value)
                elif status == "不同":
                    if messagebox.askyesno("确认", f"将远端参数 [{param_name}] 覆盖本地?"):
                        self.update_param_to_local(file_name, param_name, param_value)
            except Exception as e:
                messagebox.showerror("错误", f"同步失败: {str(e)}")

        def update_param_to_remote(self, file_name, param_name, value):
            remote_path = self.current_remote_path
            remote_file_path = os.path.join(remote_path, file_name).replace('\\', '/')
            
            success = self.ssh_client.update_remote_file(remote_file_path, param_name, value)
            if success:
                messagebox.showinfo("成功", f"远端参数 [{param_name}] 已更新")
                self.do_compare()
            else:
                messagebox.showerror("失败", f"更新远端参数 [{param_name}] 失败")

        def update_param_to_local(self, file_name, param_name, value):
            local_path = self.current_local_path
            local_file = os.path.join(local_path, file_name)
            
            try:
                with open(local_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                found, old_value = find_parameter_in_xml(content, param_name)
                if not found:
                    messagebox.showerror("错误", f"参数 [{param_name}] 在本地文件中不存在")
                    return
                
                success, new_content = update_parameter_in_xml_content(content, param_name, value)
                if success:
                    with open(local_file, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    messagebox.showinfo("成功", f"本地参数 [{param_name}] 已更新")
                    self.do_compare()
                else:
                    messagebox.showerror("失败", f"更新本地参数 [{param_name}] 失败")
            except Exception as e:
                messagebox.showerror("错误", f"本地文件操作失败: {str(e)}")
                
        def add_param_to_remote(self, file_name, param_name, value):
            remote_path = self.current_remote_path
            success = self.ssh_client.add_remote_file(
                os.path.join(remote_path, file_name), param_name, value)
            if success:
                messagebox.showinfo("成功", f"参数 [{param_name}] 已添加到远端")
                self.do_compare()
            else:
                messagebox.showerror("失败", f"添加参数 [{param_name}] 到远端失败")
        
        def add_param_to_local(self, file_name, param_name, value):
            local_path = self.current_local_path
            local_file = os.path.join(local_path, file_name)
            
            try:
                with open(local_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                success, new_content = add_parameter_in_xml_content(content, param_name, value)
                if success:
                    with open(local_file, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    messagebox.showinfo("成功", f"参数 [{param_name}] 已添加到本地")
                    self.do_compare()
                else:
                    messagebox.showerror("失败", f"添加参数 [{param_name}] 到本地失败")
            except Exception as e:
                messagebox.showerror("错误", f"本地文件操作失败: {str(e)}")
        
        def on_local_right_click(self, event):
            item_id = self.local_tree.identify_row(event.y)
            if not item_id:
                return
            
            item = self.local_tree.item(item_id)
            param_name = item['text']
            values = item['values']
            
            if not values or len(values) < 2:
                return
            
            status = values[1]
            
            menu = tk.Menu(self.root, tearoff=0)
            
            if status == "独有":
                menu.add_command(label="添加到远端", 
                                command=lambda: self.sync_selected_to_remote())
                menu.add_command(label="删除本地参数", 
                                command=lambda: self.delete_local_param(param_name, item_id))
            
            menu.post(event.x_root, event.y_root)
        
        def on_remote_right_click(self, event):
            item_id = self.remote_tree.identify_row(event.y)
            if not item_id:
                return
            
            item = self.remote_tree.item(item_id)
            param_name = item['text']
            values = item['values']
            
            if not values or len(values) < 2:
                return
            
            status = values[1]
            
            menu = tk.Menu(self.root, tearoff=0)
            
            if status == "独有":
                menu.add_command(label="添加到本地", 
                                command=lambda: self.sync_selected_to_local())
                menu.add_command(label="删除远端参数", 
                                command=lambda: self.delete_remote_param(param_name, item_id))
            
            menu.post(event.x_root, event.y_root)
        
        def delete_local_param(self, param_name, item_id):
            parent = self.local_tree.parent(item_id)
            if not parent:
                return
            file_name = self.local_tree.item(parent)['text'].strip('【】')
            
            if messagebox.askyesno("确认", f"确定删除本地参数 [{param_name}]?"):
                local_path = self.current_local_path
                local_file = os.path.join(local_path, file_name)
                
                try:
                    with open(local_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    success, new_content = delete_parameter_in_xml_content(content, param_name)
                    if success:
                        with open(local_file, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        messagebox.showinfo("成功", f"本地参数 [{param_name}] 已删除")
                        self.do_compare()
                    else:
                        messagebox.showerror("失败", f"删除本地参数 [{param_name}] 失败")
                except Exception as e:
                    messagebox.showerror("错误", f"本地文件操作失败: {str(e)}")
        
        def delete_remote_param(self, param_name, item_id):
            parent = self.remote_tree.parent(item_id)
            if not parent:
                return
            file_name = self.remote_tree.item(parent)['text'].strip('【】')
            
            if messagebox.askyesno("确认", f"确定删除远端参数 [{param_name}]?"):
                remote_path = self.current_remote_path
                success = self.ssh_client.delete_remote_file(
                    os.path.join(remote_path, file_name), param_name)
                if success:
                    messagebox.showinfo("成功", f"远端参数 [{param_name}] 已删除")
                    self.do_compare()
                else:
                    messagebox.showerror("失败", f"删除远端参数 [{param_name}] 失败")
        
        def browse_folder(self):
            if self.single_file_mode.get():
                if self.remote_mode.get():
                    self.browse_remote_file()
                else:
                    self.browse_local_file()
            else:
                if self.remote_mode.get():
                    self.browse_remote_dir()
                else:
                    folder = filedialog.askdirectory(title="选择本地XML文件夹")
                    if folder:
                        self.folder_path.set(folder)
        
        def browse_local_file(self):
            file_path = filedialog.askopenfilename(
                title="选择XML文件",
                filetypes=[("XML文件", "*.xml"), ("所有文件", "*.*")]
            )
            if file_path:
                self.file_path.set(file_path)
                self.folder_path.set(file_path)
        
        def browse_remote_dir(self):
            if not self.ssh_client or not self.ssh_client.sftp:
                messagebox.showwarning("警告", "请先连接SSH服务器")
                return
            
            dialog = tk.Toplevel(self.root)
            dialog.title("选择远程工作目录")
            dialog.geometry("600x600")
            
            ttk.Label(dialog, text="路径:").pack(pady=(10,0))
            entry = ttk.Entry(dialog, width=60)
            entry.pack(pady=5)
            entry.insert(0, self.folder_path.get() or "/")
            
            tv = ttk.Treeview(dialog, height=12)
            tv.heading("#0", text="名称")
            tv.column("#0", width=350)
            tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            def refresh_tree(path):
                tv.delete(*tv.get_children())
                try:
                    if path != "/":
                        tv.insert("", "end", text="..", values=("返回上级",))
                    for attr in self.ssh_client.sftp.listdir_attr(path):
                        if attr.st_mode & 0o170000 == 0o040000:
                            tv.insert("", "end", text=attr.filename, values=("文件夹",))
                except Exception:
                    pass
            
            def on_dbl_click(event):
                item = tv.identify_row(event.y)
                if item:
                    name = tv.item(item, "text")
                    if name == "..":
                        current_path = entry.get().rstrip("/")
                        parent_path = "/".join(current_path.split("/")[:-1]) or "/"
                        entry.delete(0, tk.END)
                        entry.insert(0, parent_path)
                        refresh_tree(parent_path)
                    else:
                        new_path = entry.get().rstrip("/") + "/" + name
                        entry.delete(0, tk.END)
                        entry.insert(0, new_path)
                        refresh_tree(new_path)
            
            tv.bind("<Double-1>", on_dbl_click)
            refresh_tree(entry.get())
            
            def on_ok():
                path = entry.get().rstrip("/")
                self.folder_path.set(path)
                dialog.destroy()
            
            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT)
        
        def browse_remote_file(self):
            if not self.ssh_client or not self.ssh_client.sftp:
                messagebox.showwarning("警告", "请先连接SSH服务器")
                return
            
            dialog = tk.Toplevel(self.root)
            dialog.title("选择远程XML文件")
            dialog.geometry("600x600")
            
            ttk.Label(dialog, text="路径:").pack(pady=(10,0))
            entry = ttk.Entry(dialog, width=60)
            entry.pack(pady=5)
            entry.insert(0, self.folder_path.get() or "/")
            
            tv = ttk.Treeview(dialog, height=12)
            tv.heading("#0", text="名称")
            tv.column("#0", width=350)
            tv.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            def refresh_tree(path):
                tv.delete(*tv.get_children())
                try:
                    if path != "/":
                        tv.insert("", "end", text="..", values=("返回上级",))
                    for attr in self.ssh_client.sftp.listdir_attr(path):
                        if attr.st_mode & 0o170000 == 0o040000:
                            tv.insert("", "end", text=attr.filename, values=("文件夹",))
                        elif attr.filename.endswith('.xml'):
                            tv.insert("", "end", text=attr.filename, values=("XML文件",))
                except Exception:
                    pass
            
            def on_dbl_click(event):
                item = tv.identify_row(event.y)
                if item:
                    name = tv.item(item, "text")
                    values = tv.item(item, "values")
                    if name == "..":
                        current_path = entry.get().rstrip("/")
                        parent_path = "/".join(current_path.split("/")[:-1]) or "/"
                        entry.delete(0, tk.END)
                        entry.insert(0, parent_path)
                        refresh_tree(parent_path)
                    elif values and values[0] == "文件夹":
                        new_path = entry.get().rstrip("/") + "/" + name
                        entry.delete(0, tk.END)
                        entry.insert(0, new_path)
                        refresh_tree(new_path)
                    elif values and values[0] == "XML文件":
                        file_path = entry.get().rstrip("/") + "/" + name
                        entry.delete(0, tk.END)
                        entry.insert(0, file_path)
                        dialog.destroy()
                        self.file_path.set(file_path)
                        self.folder_path.set(file_path)
            
            tv.bind("<Double-1>", on_dbl_click)
            refresh_tree(entry.get())
            
            def on_ok():
                path = entry.get().rstrip("/")
                if path.endswith('.xml'):
                    self.file_path.set(path)
                    self.folder_path.set(path)
                    dialog.destroy()
                else:
                    messagebox.showwarning("警告", "请选择一个XML文件")
            
            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(pady=10)
            ttk.Button(btn_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT)
        
        def get_folder(self):
            path = self.folder_path.get().strip()
            if not path:
                if self.single_file_mode.get():
                    messagebox.showwarning("警告", "请先选择XML文件")
                else:
                    messagebox.showwarning("警告", "请先选择工作目录")
                return None
            if self.remote_mode.get():
                if not self.ssh_client or not self.ssh_client.client:
                    messagebox.showwarning("警告", "请先连接SSH服务器")
                    return None
            elif self.single_file_mode.get():
                if not os.path.exists(path):
                    messagebox.showwarning("警告", "文件不存在")
                    return None
            elif not os.path.exists(path):
                messagebox.showwarning("警告", "目录不存在")
                return None
            return path
        
        def do_find_file(self, file_path, param_name):
            self.status_label.config(text="正在查找...")
            self.text_find_result.delete(1.0, tk.END)
            def run():
                try:
                    if self.remote_mode.get():
                        content = self.ssh_client.read_remote_file(file_path)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    if content:
                        found, value = find_parameter_in_xml(content, param_name)
                        if found:
                            self.root.after(0, lambda: self.show_find_file_result(file_path, value))
                        else:
                            self.root.after(0, lambda: self.show_find_file_result(file_path, None))
                    else:
                        self.root.after(0, lambda: self.show_find_file_result(file_path, None))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"读取文件失败: {str(e)}"))
            threading.Thread(target=run, daemon=True).start()
        
        def show_find_file_result(self, file_path, value):
            if value is not None:
                self.text_find_result.insert(tk.END, f"文件: {file_path}\n值: {value}\n")
                self.status_label.config(text="查找完成")
            else:
                self.text_find_result.insert(tk.END, f"文件: {file_path}\n未找到该参数\n")
                self.status_label.config(text="未找到该参数")
        
        def do_delete_file(self, file_path, param_name):
            if not messagebox.askyesno("确认", f"确定要删除参数 '{param_name}' 吗?"):
                return
            self.status_label.config(text="正在删除...")
            self.text_delete_result.delete(1.0, tk.END)
            def run():
                try:
                    if self.remote_mode.get():
                        content = self.ssh_client.read_remote_file(file_path)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    if content:
                        success, new_content = delete_parameter_in_xml_content(content, param_name)
                        if success:
                            if self.remote_mode.get():
                                self.ssh_client.write_remote_file(file_path, new_content)
                            else:
                                with open(file_path, 'w', encoding='utf-8') as f:
                                    f.write(new_content)
                            self.root.after(0, lambda: self.show_delete_file_result(True))
                        else:
                            self.root.after(0, lambda: self.show_delete_file_result(False))
                    else:
                        self.root.after(0, lambda: self.show_delete_file_result(False))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"操作失败: {str(e)}"))
            threading.Thread(target=run, daemon=True).start()
        
        def show_delete_file_result(self, success):
            if success:
                self.text_delete_result.insert(tk.END, "删除完成\n")
                self.status_label.config(text="删除完成")
            else:
                self.text_delete_result.insert(tk.END, "未找到该参数或删除失败\n")
                self.status_label.config(text="删除失败")
        
        def do_update_file(self, file_path, param_name, new_value):
            self.status_label.config(text="正在修改...")
            self.text_update_result.delete(1.0, tk.END)
            def run():
                try:
                    if self.remote_mode.get():
                        content = self.ssh_client.read_remote_file(file_path)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    if content:
                        success, new_content = update_parameter_in_xml_content(content, param_name, new_value)
                        if success:
                            if self.remote_mode.get():
                                self.ssh_client.write_remote_file(file_path, new_content)
                            else:
                                with open(file_path, 'w', encoding='utf-8') as f:
                                    f.write(new_content)
                            self.root.after(0, lambda: self.show_update_file_result(True))
                        else:
                            self.root.after(0, lambda: self.show_update_file_result(False))
                    else:
                        self.root.after(0, lambda: self.show_update_file_result(False))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"操作失败: {str(e)}"))
            threading.Thread(target=run, daemon=True).start()
        
        def show_update_file_result(self, success):
            if success:
                self.text_update_result.insert(tk.END, "修改完成\n")
                self.status_label.config(text="修改完成")
            else:
                self.text_update_result.insert(tk.END, "未找到该参数或修改失败\n")
                self.status_label.config(text="修改失败")
        
        def do_add_file(self, file_path, param_name, value, comment=None):
            self.status_label.config(text="正在添加...")
            self.text_add_result.delete(1.0, tk.END)
            def run():
                try:
                    if self.remote_mode.get():
                        content = self.ssh_client.read_remote_file(file_path)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    if content:
                        success, new_content = add_parameter_in_xml_content(content, param_name, value, comment)
                        if success:
                            if self.remote_mode.get():
                                self.ssh_client.write_remote_file(file_path, new_content)
                            else:
                                with open(file_path, 'w', encoding='utf-8') as f:
                                    f.write(new_content)
                            self.root.after(0, lambda: self.show_add_file_result(True))
                        else:
                            self.root.after(0, lambda: self.show_add_file_result(False))
                    else:
                        self.root.after(0, lambda: self.show_add_file_result(False))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"操作失败: {str(e)}"))
            threading.Thread(target=run, daemon=True).start()
        
        def show_add_file_result(self, success):
            if success:
                self.text_add_result.insert(tk.END, "添加完成\n")
                self.status_label.config(text="添加完成")
            else:
                self.text_add_result.insert(tk.END, "参数已存在或添加失败\n")
                self.status_label.config(text="添加失败")
        
        def do_list_file(self, file_path):
            self.status_label.config(text="正在列出...")
            self.text_list_result.delete(1.0, tk.END)
            def run():
                try:
                    if self.remote_mode.get():
                        content = self.ssh_client.read_remote_file(file_path)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    if content:
                        params = list_parameters_in_xml(content)
                        self.root.after(0, lambda: self.show_list_file_result(params))
                    else:
                        self.root.after(0, lambda: self.show_list_file_result(None))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"读取文件失败: {str(e)}"))
            threading.Thread(target=run, daemon=True).start()
        
        def show_list_file_result(self, params):
            if params:
                self.text_list_result.insert(tk.END, f"共找到 {len(params)} 个参数:\n\n")
                for name, value in params:
                    self.text_list_result.insert(tk.END, f"{name}: {value}\n")
                self.status_label.config(text=f"列出完成: {len(params)} 个参数")
            else:
                self.text_list_result.insert(tk.END, "未找到任何参数或读取失败\n")
                self.status_label.config(text="未找到任何参数")
        
        def do_find(self):
            path = self.get_folder()
            if not path:
                return
            param_name = self.entry_find_name.get().strip()
            if not param_name:
                messagebox.showwarning("警告", "请输入参数名")
                return
            if self.single_file_mode.get():
                self.do_find_file(path, param_name)
                return
            self.status_label.config(text="正在查找...")
            self.text_find_result.delete(1.0, tk.END)
            filename_filter = self.get_filename_filter()
            def run():
                if self.remote_mode.get():
                    results = self.ssh_client.find_remote(path, param_name, filename_filter)
                else:
                    results = find_parameter_in_folder(path, param_name, filename_filter)
                self.root.after(0, lambda: self.show_find_results(results))
            threading.Thread(target=run, daemon=True).start()
        
        def show_find_results(self, results):
            if results:
                self.text_find_result.insert(tk.END, f"找到 {len(results)} 处:\n\n")
                for file_path, value in results:
                    self.text_find_result.insert(tk.END, f"文件: {file_path}\n值: {value}\n\n")
                self.status_label.config(text=f"查找完成: 找到 {len(results)} 处")
            else:
                self.text_find_result.insert(tk.END, "未找到该参数")
                self.status_label.config(text="未找到该参数")
        
        def do_delete(self):
            path = self.get_folder()
            if not path:
                return
            param_name = self.entry_delete_name.get().strip()
            if not param_name:
                messagebox.showwarning("警告", "请输入参数名")
                return
            if self.single_file_mode.get():
                self.do_delete_file(path, param_name)
                return
            if not messagebox.askyesno("确认", f"确定要删除参数 '{param_name}' 吗?"):
                return
            self.status_label.config(text="正在删除...")
            self.text_delete_result.delete(1.0, tk.END)
            filename_filter = self.get_filename_filter()
            def run():
                if self.remote_mode.get():
                    success, total = self.ssh_client.delete_remote_folder(path, param_name, filename_filter)
                else:
                    success, total = delete_parameter_in_folder(path, param_name, filename_filter)
                self.root.after(0, lambda: self.show_delete_results(success, total))
            threading.Thread(target=run, daemon=True).start()
        
        def show_delete_results(self, success, total):
            self.text_delete_result.insert(tk.END, f"删除完成\n成功处理: {success}/{total} 个文件\n")
            self.status_label.config(text=f"删除完成: 成功处理 {success}/{total} 个文件")
        
        def do_update(self):
            path = self.get_folder()
            if not path:
                return
            param_name = self.entry_update_name.get().strip()
            new_value = self.entry_update_value.get().strip()
            if not param_name or not new_value:
                messagebox.showwarning("警告", "请输入参数名和新值")
                return
            if self.single_file_mode.get():
                self.do_update_file(path, param_name, new_value)
                return
            self.status_label.config(text="正在修改...")
            self.text_update_result.delete(1.0, tk.END)
            filename_filter = self.get_filename_filter()
            def run():
                if self.remote_mode.get():
                    success, total = self.ssh_client.update_remote_folder(path, param_name, new_value, filename_filter)
                else:
                    success, total = update_parameter_in_folder(path, param_name, new_value, filename_filter)
                self.root.after(0, lambda: self.show_update_results(success, total))
            threading.Thread(target=run, daemon=True).start()
        
        def show_update_results(self, success, total):
            self.text_update_result.insert(tk.END, f"修改完成\n成功处理: {success}/{total} 个文件\n")
            self.status_label.config(text=f"修改完成: 成功处理 {success}/{total} 个文件")
        
        def do_add(self):
            path = self.get_folder()
            if not path:
                return
            param_name = self.entry_add_name.get().strip()
            value = self.entry_add_value.get().strip()
            comment = self.entry_add_comment.get().strip() or None
            if not param_name or not value:
                messagebox.showwarning("警告", "请输入参数名和参数值")
                return
            if self.single_file_mode.get():
                self.do_add_file(path, param_name, value, comment)
                return
            self.status_label.config(text="正在添加...")
            self.text_add_result.delete(1.0, tk.END)
            filename_filter = self.get_filename_filter()
            def run():
                if self.remote_mode.get():
                    success, total = self.ssh_client.add_remote_folder(path, param_name, value, comment, filename_filter)
                else:
                    success, total = add_parameter_in_folder(path, param_name, value, comment, filename_filter)
                self.root.after(0, lambda: self.show_add_results(success, total))
            threading.Thread(target=run, daemon=True).start()
        
        def show_add_results(self, success, total):
            self.text_add_result.insert(tk.END, f"添加完成\n成功处理: {success}/{total} 个文件\n")
            self.status_label.config(text=f"添加完成: 成功处理 {success}/{total} 个文件")
        
        def do_list(self):
            path = self.get_folder()
            if not path:
                return
            if self.single_file_mode.get():
                self.do_list_file(path)
                return
            self.status_label.config(text="正在列出...")
            self.text_list_result.delete(1.0, tk.END)
            filename_filter = self.get_filename_filter()
            def run():
                if self.remote_mode.get():
                    all_params = self.ssh_client.list_remote_all(path, filename_filter)
                else:
                    all_params = collect_local_params(path, filename_filter)
                self.root.after(0, lambda: self.show_list_results(all_params))
            threading.Thread(target=run, daemon=True).start()
        
        def show_list_results(self, all_params):
            if all_params:
                self.text_list_result.insert(tk.END, f"共找到 {len(all_params)} 个不同参数:\n\n")
                for name in sorted(all_params.keys()):
                    self.text_list_result.insert(tk.END, f"{name}: {all_params[name]}\n")
                self.status_label.config(text=f"列出完成: {len(all_params)} 个参数")
            else:
                self.text_list_result.insert(tk.END, "未找到任何参数")
                self.status_label.config(text="未找到任何参数")
    
    def main_gui():
        root = tk.Tk()
        app = XMLParameterTool(root)
        root.mainloop()


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def main_cli():
    clear_screen()
    print("=" * 50)
    print("       XML参数管理工具")
    print("=" * 50)
    print("  1. 本地模式")
    print("  2. 远程模式(SSH)")
    print("  0. 退出")
    print("-" * 50)
    
    mode = input("\n请选择模式: ").strip()
    
    folder_path = input("\n请输入文件夹路径: ").strip()
    if not folder_path:
        return
    
    ssh_client = None
    
    if mode == '2':
        print("\n--- SSH连接信息 ---")
        host = input("主机: ").strip()
        port = int(input("端口 [22]: ").strip() or 22)
        user = input("用户名: ").strip()
        password = input("密码: ").strip()
        
        ssh_client = SSHClient(host, port, user, password)
        success, msg = ssh_client.connect()
        print(msg)
        if not success:
            return
    
    clear_screen()
    print(f"当前目录: {folder_path}")
    print("=" * 50)
    print("  1. 查找参数")
    print("  2. 删除参数")
    print("  3. 修改参数")
    print("  4. 添加参数")
    print("  5. 列出所有参数")
    print("  0. 退出")
    print("-" * 50)
    
    while True:
        choice = input("\n请选择操作: ").strip()
        
        if choice == '0':
            if ssh_client:
                ssh_client.disconnect()
            print("程序已退出")
            break
        elif choice == '1':
            param_name = input("参数名: ").strip()
            if param_name:
                if ssh_client:
                    results = ssh_client.find_remote(folder_path, param_name)
                else:
                    results = find_parameter_in_folder(folder_path, param_name)
                if results:
                    print(f"\n找到 {len(results)} 处:")
                    for fp, val in results:
                        print(f"  {fp}: {val}")
                else:
                    print("未找到")
            input("\n按回车继续...")
        elif choice == '2':
            param_name = input("参数名: ").strip()
            if param_name and input("确认删除? (y/n): ").strip().lower() == 'y':
                if ssh_client:
                    s, t = ssh_client.delete_remote_folder(folder_path, param_name)
                else:
                    s, t = delete_parameter_in_folder(folder_path, param_name)
                print(f"删除完成: {s}/{t}")
            input("\n按回车继续...")
        elif choice == '3':
            param_name = input("参数名: ").strip()
            new_value = input("新值: ").strip()
            if param_name and new_value:
                if ssh_client:
                    s, t = ssh_client.update_remote_folder(folder_path, param_name, new_value)
                else:
                    s, t = update_parameter_in_folder(folder_path, param_name, new_value)
                print(f"修改完成: {s}/{t}")
            input("\n按回车继续...")
        elif choice == '4':
            param_name = input("参数名: ").strip()
            value = input("参数值: ").strip()
            comment = input("注释(回车跳过): ").strip() or None
            if param_name and value:
                if ssh_client:
                    s, t = ssh_client.add_remote_folder(folder_path, param_name, value, comment)
                else:
                    s, t = add_parameter_in_folder(folder_path, param_name, value, comment)
                print(f"添加完成: {s}/{t}")
            input("\n按回车继续...")
        elif choice == '5':
            if ssh_client:
                all_params = ssh_client.list_remote_all(folder_path)
            else:
                all_params = {}
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        if file.endswith('.xml'):
                            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                content = f.read()
                            for name, value in list_parameters_in_xml(content):
                                if name not in all_params:
                                    all_params[name] = set()
                                all_params[name].add(value)
            if all_params:
                print(f"\n共 {len(all_params)} 个参数:")
                for name in sorted(all_params.keys()):
                    print(f"  {name}: {all_params[name]}")
            input("\n按回车继续...")


def main():
    if GUI_AVAILABLE:
        main_gui()
    else:
        main_cli()


if __name__ == "__main__":
    main()