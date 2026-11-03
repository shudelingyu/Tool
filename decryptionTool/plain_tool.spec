# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：Windows 与 Linux 通用
# Windows: pyinstaller --clean --noconfirm plain_tool.spec  ->  dist/PlainTool.exe
# Linux:   pyinstaller --clean --noconfirm plain_tool.spec  ->  dist/PlainTool

a = Analysis(
    ['plain_tool_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PlainTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
