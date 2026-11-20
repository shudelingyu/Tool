# -*- mode: python ; coding: utf-8 -*-
"""LogLens PyInstaller 打包配置（onefile 单文件）。

在本目录执行：
    python -m PyInstaller --noconfirm --clean LogLens.spec

输出：
    dist/LogLens.exe
"""

from pathlib import Path

PROJECT_DIR = Path(SPECPATH).resolve()

a = Analysis(
    [str(PROJECT_DIR / "main.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[
        (str(PROJECT_DIR / "assets" / "loglens.ico"), "assets"),
        (str(PROJECT_DIR / "assets" / "loglens.png"), "assets"),
        (str(PROJECT_DIR / "assets" / "screenshot.png"), "assets"),
        (str(PROJECT_DIR / "assets" / "screenshot_project.png"), "assets"),
        (str(PROJECT_DIR / "assets" / "screenshot_project_field.png"), "assets"),
        (str(PROJECT_DIR / "samples"), "samples"),
        (str(PROJECT_DIR / "README.md"), "."),
    ],
    hiddenimports=["chardet"],
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
    name="LogLens",
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
    icon=[str(PROJECT_DIR / "assets" / "loglens.ico")],
)
