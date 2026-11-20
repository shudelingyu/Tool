"""PoseView 入口。"""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from poseview.main_window import PoseViewWindow
from poseview.theme import app_stylesheet


def main() -> None:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("PoseView")
    app.setOrganizationName("PoseView")
    app.setStyleSheet(app_stylesheet())

    window = PoseViewWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
