import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from widgets import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = Path(__file__).parent / "gamehub.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
