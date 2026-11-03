import json
import os
import sys
from pathlib import Path

# 定义库文件/二进制文件扩展名黑名单（可根据需要增删）
BLACKLIST_EXTENSIONS = {
    # 编译产物
    '.so', '.dylib', '.dll', '.lib', '.a', '.o', '.obj', '.exe',
    '.pdb', '.exp', '.ilk', '.def',
    # 二进制数据
    '.bin', '.dat', '.db', '.sqlite', '.mdb',
    # 图片、音视频、压缩包等（通常不需要备份为文本）
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp',
    '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.flac', '.wav',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.iso', '.img',
    # 文档类（可能包含二进制）
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    # 其他可执行或机器码
    '.class', '.jar', '.pyc', '.pyo',
    # 无后缀文件
    '',
}

# 转换记录清单：记录「目标文件 -> 原始文件」的相对路径，供 restore_from_plain.py 精确还原
# 用 .json 是因为本机实测 .txt 也会被加密，.json 写出为明文
MANIFEST_NAME = 'plain_copy_map.json'


def normalize_suffix(suffix):
    """把用户输入的后缀规范化为带前导点的形式，如 xml -> .xml、.cpp -> .cpp"""
    suffix = suffix.strip()
    if not suffix:
        return ''
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    return suffix


def is_blacklisted(file_path):
    """根据扩展名判断是否在黑名单中"""
    return file_path.suffix.lower() in BLACKLIST_EXTENSIONS


def load_manifest(root_dir):
    """读取已有清单，返回 {目标相对路径: 原始相对路径}"""
    manifest_path = root_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return {str(dst): str(src) for dst, src in data.items()}
    except Exception as e:
        print(f"读取已有清单失败（将重新生成）：{e}")
    return {}


def save_manifest(root_dir, entries):
    """写回 JSON 清单，格式为 {目标相对路径: 原始相对路径}"""
    manifest_path = root_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')


def copy_to_plain(folder_path, target_suffix, delete_mode='ask', should_stop=None):
    """delete_mode: ask=逐个询问，yes=直接删除原文件，no=全部保留；should_stop 用于协作式停止"""
    root_dir = Path(folder_path)
    if not root_dir.is_dir():
        print(f"错误：'{folder_path}' 不是有效目录")
        return False

    target_suffix = normalize_suffix(target_suffix)
    if not target_suffix:
        print("错误：目标后缀不能为空")
        return False

    entries = load_manifest(root_dir)
    converted = skipped = failed = 0
    stopped = False

    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if should_stop and should_stop():
                stopped = True
                break

            src_path = Path(dirpath) / filename

            # 跳过清单文件本身
            if src_path.name == MANIFEST_NAME:
                continue

            # 1. 本身就是目标后缀的文件直接忽略（避免重复处理）
            if src_path.suffix.lower() == target_suffix.lower():
                print(f"跳过（本身已是 {target_suffix}）：{src_path}")
                skipped += 1
                continue

            # 2. 黑名单扩展名跳过
            if is_blacklisted(src_path):
                print(f"跳过黑名单文件：{src_path}")
                skipped += 1
                continue

            # 3. 直接替换后缀，而不是在文件名后追加
            dst_path = src_path.with_suffix(target_suffix)

            # 4. 目标已存在时跳过，避免 a.hpp / a.hxx 这类同目录同名互相覆盖
            if dst_path.exists():
                print(f"跳过（目标文件已存在）：{src_path} -> {dst_path}")
                skipped += 1
                continue

            # 5. 复制内容（二进制模式确保原样）
            try:
                with open(src_path, 'rb') as f_in, open(dst_path, 'wb') as f_out:
                    f_out.write(f_in.read())
                print(f"已转换：{src_path} -> {dst_path}")
            except Exception as e:
                print(f"转换失败 {src_path}: {e}")
                failed += 1
                continue

            # 6. 记录映射关系，供 restore 还原原始后缀
            entries[str(dst_path.relative_to(root_dir))] = str(src_path.relative_to(root_dir))
            save_manifest(root_dir, entries)
            converted += 1

            # 7. 删除原文件（按 delete_mode 处理）
            if delete_mode == 'yes':
                try:
                    src_path.unlink()
                    print(f"已删除：{src_path}")
                except Exception as e:
                    print(f"删除失败 {src_path}: {e}")
            elif delete_mode == 'ask':
                response = input(f"是否删除原文件 '{src_path}'？(y/N): ")
                if response.lower() == 'y':
                    try:
                        src_path.unlink()
                        print(f"已删除：{src_path}")
                    except Exception as e:
                        print(f"删除失败 {src_path}: {e}")

        if stopped:
            break

    print(f"\n完成：转换 {converted} 个，跳过 {skipped} 个，失败 {failed} 个" + ("（已停止）" if stopped else ""))
    if converted:
        print(f"映射清单：{root_dir / MANIFEST_NAME}")
    return True


def main(argv=None, should_stop=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("用法：python copy_to_plain.py <目标文件夹> <目标后缀> [--auto | --keep]")
        print("示例：python copy_to_plain.py D:\\depends\\pin_src urdf")
        print("      python copy_to_plain.py D:\\depends\\pin_src .cpp --auto")
        print("  <目标后缀>  直接替换原文件后缀，如 hxx -> urdf")
        print("  --auto      自动删除原始文件，无需逐个确认")
        print("  --keep      保留原始文件，不做删除询问")
        return 1
    folder = argv[0]
    suffix = argv[1]
    auto = '--auto' in argv
    keep = '--keep' in argv
    if auto and keep:
        print("错误：--auto 与 --keep 不能同时使用")
        return 1
    mode = 'yes' if auto else ('no' if keep else 'ask')
    return 0 if copy_to_plain(folder, suffix, mode, should_stop) else 1


if __name__ == '__main__':
    sys.exit(main())
