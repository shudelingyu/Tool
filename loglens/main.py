"""LogLens 启动入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from loglens import __app_name__, __app_title__, __version__
from loglens.icons import app_icon
from loglens.main_window import MainWindow
from loglens.theme import app_stylesheet, ui_family


def _debug(message: str) -> None:
    path = os.environ.get("LOGLENS_DEBUG_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def main() -> int:
    _debug(f"argv={sys.argv!r}")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_title__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("LogLens")
    app.setWindowIcon(app_icon())
    font = QFont(ui_family())
    font.setPixelSize(12)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()
    window.show()

    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        _debug(
            f"candidate={candidate!s} exists={candidate.is_file()} "
            f"size={candidate.stat().st_size if candidate.is_file() else -1}"
        )
        if candidate.is_file():
            QTimer.singleShot(0, lambda: window.load_file(str(candidate)))

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
