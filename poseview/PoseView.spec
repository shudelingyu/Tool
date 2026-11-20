# -*- mode: python ; coding: utf-8 -*-
"""PoseView PyInstaller 打包配置（onefile 单文件）。

在本目录执行：
    python -m PyInstaller --noconfirm --clean PoseView.spec

输出：
    dist/PoseView.exe
"""

from pathlib import Path

PROJECT_DIR = Path(SPECPATH).resolve()

a = Analysis(
    [str(PROJECT_DIR / "main.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[
        (str(PROJECT_DIR / "assets" / "poseview.ico"), "assets"),
        (str(PROJECT_DIR / "assets" / "poseview.png"), "assets"),
    ],
    hiddenimports=["PyQt5.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pytest",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtQml",
        "PyQt5.QtQuick",
        "PyQt5.QtMultimedia",
        "PyQt5.QtNetwork",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PoseView",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(PROJECT_DIR / "assets" / "poseview.ico")],
)
