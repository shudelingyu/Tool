import os
import shutil
from pathlib import Path

def copy_files_with_md_suffix(source_dir, target_dir, flatten_structure=False):
    """
    将源文件夹中的文件复制到目标文件夹，并在文件名后添加.md后缀
    
    参数:
        source_dir (str): 源文件夹路径
        target_dir (str): 目标文件夹路径
        flatten_structure (bool): 是否扁平化目录结构（默认False，保留目录结构）
    """
    source_path = Path(source_dir)
    target_path = Path(target_dir)
    
    # 检查源文件夹是否存在
    if not source_path.exists():
        print(f"错误：源文件夹 '{source_dir}' 不存在")
        return
    
    # 创建目标文件夹
    target_path.mkdir(parents=True, exist_ok=True)
    
    copied_count = 0
    skipped_count = 0
    
    print(f"开始从 '{source_dir}' 复制文件到 '{target_dir}'")
    print("-" * 50)
    
    # 使用os.walk递归遍历所有子文件夹
    for root, dirs, files in os.walk(source_dir):
        for filename in files:
            # 获取源文件的完整路径
            source_file = Path(root) / filename
            
            # 确定目标文件路径
            if flatten_structure:
                # 扁平化结构：所有文件都放在目标文件夹根目录
                target_file = target_path / f"{filename}.md"
            else:
                # 保持目录结构
                relative_path = source_file.relative_to(source_dir)
                target_subdir = target_path / relative_path.parent
                target_file = target_subdir / f"{filename}.md"
                # 创建子目录
                target_subdir.mkdir(parents=True, exist_ok=True)
            
            # 检查目标文件是否已存在
            if target_file.exists():
                print(f"⚠️  跳过：'{target_file}' 已存在")
                skipped_count += 1
                continue
            
            try:
                # 复制文件
                shutil.copy2(source_file, target_file)
                print(f"✅ 已复制：'{source_file}' -> '{target_file}'")
                copied_count += 1
            except Exception as e:
                print(f"❌ 错误：复制 '{source_file}' 失败: {e}")
                skipped_count += 1
    
    print("-" * 50)
    print(f"操作完成！")
    print(f"✅ 成功复制: {copied_count} 个文件")
    print(f"⚠️  跳过: {skipped_count} 个文件")
    print(f"📁 目标位置: {target_dir}")

def preview_operation(source_dir, target_dir, flatten_structure=False):
    """
    预览操作而不实际执行复制
    """
    source_path = Path(source_dir)
    
    print("预览模式 - 将显示所有更改但不实际执行复制：")
    print(f"源文件夹: {source_dir}")
    print(f"目标文件夹: {target_dir}")
    print(f"扁平化结构: {'是' if flatten_structure else '否'}")
    print("-" * 50)
    
    file_count = 0
    
    for root, dirs, files in os.walk(source_dir):
        for filename in files:
            source_file = Path(root) / filename
            
            if flatten_structure:
                target_file = Path(target_dir) / f"{filename}.md"
            else:
                relative_path = source_file.relative_to(source_dir)
                target_subdir = Path(target_dir) / relative_path.parent
                target_file = target_subdir / f"{filename}.md"
            
            print(f"📄 将复制: {source_file.relative_to(source_dir)}")
            print(f"   ➡ 变为: {target_file.relative_to(Path(target_dir))}")
            file_count += 1
    
    print("-" * 50)
    print(f"总计将复制: {file_count} 个文件")
    return file_count

if __name__ == "__main__":
    # 获取用户输入
    source_folder = input("请输入源文件夹路径（直接回车使用当前目录）: ").strip()
    if not source_folder:
        source_folder = "."
    
    target_folder = input("请输入目标文件夹路径: ").strip()
    if not target_folder:
        print("错误：必须指定目标文件夹路径")
        exit(1)
    
    # 选择是否扁平化目录结构
    flatten_choice = input("是否扁平化目录结构？(y/N): ").strip().lower()
    flatten_structure = (flatten_choice == 'y')
    
    # 选择操作模式
    mode_choice = input("\n请选择模式：\n1. 预览模式（只显示更改）\n2. 执行模式（实际复制文件）\n请输入选择（1或2）: ").strip()
    
    if mode_choice == "1":
        file_count = preview_operation(source_folder, target_folder, flatten_structure)
        if file_count > 0:
            confirm = input(f"\n确认要复制 {file_count} 个文件吗？(y/N): ").strip().lower()
            if confirm == 'y':
                copy_files_with_md_suffix(source_folder, target_folder, flatten_structure)
            else:
                print("操作已取消")
        else:
            print("没有找到可复制的文件")
    elif mode_choice == "2":
        copy_files_with_md_suffix(source_folder, target_folder, flatten_structure)
    else:
        print("无效选择，退出程序")