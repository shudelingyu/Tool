# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['InstTool.py'],  # 你的主脚本文件名
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'cv2',  # OpenCV库
        'socket', 'threading', 'struct',  # 标准库
        'tkinter', 'PIL', # GUI库
        'datetime', 'logging', 'os', 'time', 'queue' # 其他标准库
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='InstTool',  # 生成的exe名称
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 使用UPX压缩
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='tools.ico',  # 可选的图标文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='InstTool',  # 文件夹名称
)