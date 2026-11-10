import faulthandler
import os
import sys

from PyQt5.QtWidgets import QApplication

from main_window import MainWindow

if __name__ == "__main__":
    # 原生崩溃（如访问冲突）也写入 crash.log，便于定位
    try:
        _crash = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_crash)
    except OSError:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
