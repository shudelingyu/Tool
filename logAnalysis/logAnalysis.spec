# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 收集 pyarrow 的数据文件（支持 parquet 读写）
pyarrow_datas = collect_data_files('pyarrow')
pyarrow_hiddenimports = collect_submodules('pyarrow')

a = Analysis(
    ['logAnalysis.py'],
    pathex=[],
    binaries=[],
    datas=pyarrow_datas,
    hiddenimports=[
        'pyarrow',
        'pyarrow.lib',
        'paramiko',
        'paramiko.transport',
        'paramiko.client',
        'PyQt5.QtCore',
        'PyQt5.QtWidgets',
        'pyqtgraph',
        'pandas',
        'numpy',
        'datetime',
        'collections',
        're',
        'os',
        'sys',
        'queue',
        'threading',
        'time',
        'socket',
        'struct',
        'hashlib',
        'weakref',
        'codecs',
        'logging',
        'io',
        'signal',
        'errno',
        'fcntl',
        'termios',
        'resource',
        'pwd',
        'grp',
        'select',
        'functools',
        'itertools',
        'math',
        'random',
        'string',
        'tempfile',
        'subprocess',
        'json',
        'pickle',
        'copy',
        'warnings',
        'enum',
        'types',
        'abc',
        'contextlib',
        'importlib',
        'inspect',
        'ast',
        'builtins',
        'cffi',
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.asymmetric',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.kdf',
        'cryptography.utils',
        'bcrypt',
        'nacl',
        'nacl.bindings',
        'nacl.encoding',
        'nacl.public',
        'nacl.secret',
        'nacl.sign',
        'nacl.utils',
    ] + pyarrow_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    exclude_binaries=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='logAnalysis',  # 生成的exe名称
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
    icon='logAnalysis.ico',  # 可选的图标文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LogAnalysis',  # 文件夹名称
)