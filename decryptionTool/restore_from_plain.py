import json
import os
import sys
from pathlib import Path

# 与 copy_to_plain.py 保持一致
MANIFEST_NAME = 'plain_copy_map.json'


def normalize_suffix(suffix):
    """把用户输入的后缀规范化为带前导点的形式，如 urdf -> .urdf"""
    suffix = suffix.strip()
    if not suffix:
        return ''
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    return suffix


def rename_with_confirm(src_path, dst_path, mode='ask'):
    """把 src_path 改名为 dst_path；mode: ask=询问，force=直接覆盖，skip=存在则跳过"""
    if dst_path.exists():
        if mode == 'force':
            print(f"覆盖：{dst_path}")
        elif mode == 'skip':
            print(f"跳过（目标已存在）：{src_path} -> {dst_path}")
            return False
        else:
            response = input(f"目标文件 '{dst_path}' 已存在，是否覆盖？(y/N): ")
            if response.lower() != 'y':
                print(f"跳过：{src_path}")
                return False
    try:
        os.replace(str(src_path), str(dst_path))
        print(f"已恢复：{src_path} -> {dst_path}")
        return True
    except Exception as e:
        print(f"恢复失败 {src_path}: {e}")
        return False


def restore_from_manifest(root_dir, mode='ask', should_stop=None):
    """按清单把「目标后缀文件」还原为「原始后缀文件」"""
    manifest_path = root_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"未找到映射清单：{manifest_path}")
        print("可用 --from <当前后缀> --to <原始后缀> 手动指定后缀还原")
        return False

    try:
        entries = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(entries, dict):
            raise ValueError("清单格式不是对象")
    except Exception as e:
        print(f"读取清单失败：{e}")
        return False

    remaining = {}
    stopped = False
    for dst_rel, src_rel in entries.items():
        if stopped or (should_stop and should_stop()):
            stopped = True
            remaining[dst_rel] = src_rel
            continue

        dst_path = root_dir / dst_rel
        src_path = root_dir / src_rel

        if not dst_path.exists():
            print(f"跳过（文件不存在）：{dst_path}")
            continue
        if not rename_with_confirm(dst_path, src_path, mode):
            remaining[dst_rel] = src_rel

    if remaining:
        manifest_path.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding='utf-8')
        if stopped:
            print(f"\n已停止：还有 {len(remaining)} 项未恢复，清单已保留")
        else:
            print(f"\n仍有 {len(remaining)} 项未恢复，清单已保留")
    else:
        manifest_path.unlink()
        print("\n全部恢复完成，清单已删除")
    return True


def restore_by_suffix(root_dir, from_suffix, to_suffix, mode='ask', should_stop=None):
    """不依赖清单：把该目录下 from_suffix 的文件统一改回 to_suffix"""
    from_suffix = normalize_suffix(from_suffix)
    to_suffix = normalize_suffix(to_suffix)
    if not from_suffix or not to_suffix:
        print("错误：--from / --to 后缀不能为空")
        return False
    if from_suffix.lower() == to_suffix.lower():
        print("错误：--from 与 --to 不能相同")
        return False

    restored = skipped = 0
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
            if src_path.suffix.lower() != from_suffix.lower():
                continue

            dst_path = src_path.with_suffix(to_suffix)
            if rename_with_confirm(src_path, dst_path, mode):
                restored += 1
            else:
                skipped += 1

        if stopped:
            break

    print(f"\n完成：恢复 {restored} 个，跳过 {skipped} 个" + ("（已停止）" if stopped else ""))
    return True


def main(argv=None, should_stop=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 1:
        print("用法：")
        print("  按清单还原：python restore_from_plain.py <目标文件夹> [--force | --skip]")
        print("  按后缀还原：python restore_from_plain.py <目标文件夹> --from <当前后缀> --to <原始后缀> [--force | --skip]")
        print("示例：python restore_from_plain.py D:\\depends\\pin_src")
        print("      python restore_from_plain.py D:\\depends\\pin_src --from urdf --to hxx --force")
        print("  --force  目标已存在时直接覆盖")
        print("  --skip   目标已存在时跳过，不做询问")
        return 1

    folder = argv[0]
    args = argv[1:]
    force = '--force' in args
    skip = '--skip' in args
    if force and skip:
        print("错误：--force 与 --skip 不能同时使用")
        return 1
    mode = 'force' if force else ('skip' if skip else 'ask')
    from_ext = None
    to_ext = None

    i = 0
    while i < len(args):
        if args[i] == '--from' and i + 1 < len(args):
            from_ext = args[i + 1]
            i += 2
        elif args[i] == '--to' and i + 1 < len(args):
            to_ext = args[i + 1]
            i += 2
        elif args[i] in ('--force', '--skip'):
            i += 1
        else:
            print(f"未知参数：{args[i]}")
            return 1

    root = Path(folder)
    if not root.is_dir():
        print(f"错误：'{folder}' 不是有效目录")
        return 1

    if to_ext:
        if not from_ext:
            print("错误：使用 --to 时必须同时指定 --from")
            return 1
        ok = restore_by_suffix(root, from_ext, to_ext, mode, should_stop)
    else:
        ok = restore_from_manifest(root, mode, should_stop)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
