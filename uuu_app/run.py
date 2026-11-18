import os
import sys

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")

if getattr(sys, "frozen", False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

icon_path = os.path.abspath(os.path.join(base_path, "..", "icons", "i_firm.svg"))

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from uuu_app import cfg
    from uuu_app.app import FlasherFarmApp
    from uuu_app.qt import QtWidgets, QtGui
else:
    from . import cfg
    from .app import FlasherFarmApp
    from .qt import QtWidgets, QtGui

def main():
    app = QtWidgets.QApplication([])
    app.setApplicationName("Firmware Flash Tool")
    app.setDesktopFileName("Firmware_Flash_Tool")
    desktop_file = os.path.expanduser("~/.local/share/applications/Firmware_Flash_Tool.desktop")
    if not os.path.exists(desktop_file):
        app.setWindowIcon(QtGui.QIcon(icon_path))
    cfg.load_stylesheet(app)
    window = FlasherFarmApp()
    window.show()
    app.exec()

if __name__ == "__main__":
    main()
