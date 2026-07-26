"""Application bootstrap: wizard on first run, main window after."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import config
from .main_window import MainWindow
from .wizard import SetupWizard


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("CiteTool")
    cfg = config.load()
    if not cfg.get("setup_complete"):
        wizard = SetupWizard(cfg)
        if not wizard.exec():
            return 0            # user cancelled setup
        cfg = config.load()
    win = MainWindow(cfg)
    win.show()
    return app.exec()
