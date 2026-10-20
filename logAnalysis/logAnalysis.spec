# -*- mode: python ; coding: utf-8 -*-
"""LogAnalysis 打包配置

要点：
- upx=False：UPX 压缩 Qt / 原生 DLL 会导致在其他电脑上静默崩溃
- datas 内置 configs/data_formats.json：exe 单独拷贝到其他电脑也能解析日志
- datas 内置 logAnalysis.ico：运行时窗口/任务栏图标与 exe 图标保持一致
- 不再打包 pyarrow：缓存已改用 pickle，去掉该原生依赖可显著减小体积并消除崩溃面
"""
import sys

block_cipher = None

# 把数据格式配置与图标一并打包，保证 exe 单独拷贝到其他电脑后仍能解析日志、正常显示图标
config_datas = [('configs/data_formats.json', 'configs'),
                ('logAnalysis.ico', '.')]

a = Analysis(
    ['logAnalysis.py'],
    pathex=[],
    binaries=[],
    datas=config_datas,
    hiddenimports=[
        'json',
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
    ],
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
    upx=False,  # 关闭 UPX：压缩 Qt/原生 DLL 会导致换机后静默崩溃
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口（运行日志写入 logs/logAnalysis.log）
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
    upx=False,  # 同上：避免 UPX 压缩导致换机后崩溃
    upx_exclude=[],
    name='LogAnalysis',  # 文件夹名称
)