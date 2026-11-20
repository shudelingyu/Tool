"""LogLens 源码启动器（用于 E-SafeNet 等透明加密环境）。

双击本文件，或用受信任的 Python 启动：

    pythonw.exe run_loglens.pyw
    pythonw.exe run_loglens.pyw D:\\path\\to\\main.log

在加密软件按进程白名单解密的机器上，python.exe / pythonw.exe 通常受信任，
可以正常读取被加密的 .log；打包后的 exe 需要单独加入白名单。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.argv[0] = str(ROOT / "main.py")
runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
