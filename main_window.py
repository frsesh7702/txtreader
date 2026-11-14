"""主窗口：仿「朗读女」布局的 TXT 朗读器。"""
import os
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPalette,
                         QPixmap, QTextCursor)
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QDialog,
                             QFileDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox,
                             QProgressDialog, QPushButton, QSlider, QSpinBox,
                             QStyle, QTextEdit, QVBoxLayout, QWidget)

import config
from baidu_tts import BaiduTTS, VOICES, split_text
from player import Player
from settings_dialog import SettingsDialog
from prefs_dialog import PrefsDialog


class PlaylistWindow(QDialog):
    """悬浮的朗读列表窗口（非模态，关闭即隐藏）。"""

    def __init__(self, mw):
        super().__init__(mw, Qt.Tool)
        self.setWindowTitle("朗读列表")
        self.resize(320, 440)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("朗读列表（双击载入）"))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(mw._load_item)
        lay.addWidget(self.list)
        btns = QHBoxLayout()
        for text, fn in (("＋添加", mw._add_files), ("✕删除", mw._del_file),
                         ("清空", mw._clear_playlist), ("关闭", self.hide)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)

    def closeEvent(self, e):
        e.ignore()
        self.hide()

WELCOME = """使用须知：
1. 本软件使用「百度智能云 · 语音合成」免费额度，请先点击菜单【选项 → 百度语音设置】填入 API Key / Secret Key（对话框内有图文申请指引）。
2. 点击右下方【📋 朗读列表】弹出列表窗口，把 txt 小说加入列表；双击列表项载入全文。
3. 点击【▶ 播放】开始朗读；朗读时当前段落会以黄色高亮。
4. 【生成声音文件】可把全文导出为 MP3。
5. 伴音（背景音乐）与阅读区背景在菜单栏【设置】中调整。

提示：把小说 txt 直接拖到本窗口也可以加入朗读列表。
"""


class SeekSlider(QSlider):
    """仿 PotPlayer 播放器的细黄线进度条：点击/拖动可直接跳转。"""

    seek_requested = pyqtSignal(int)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > self.minimum():
            self.setSliderDown(True)
            self._jump(e.pos().x())
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self._jump(e.pos().x())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            self.seek_requested.emit(self.value())
            return
        super().mouseReleaseEvent(e)

    def _jump(self, x):
        v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                           x, max(1, self.width()))
        self.setValue(v)


class SubtitleWindow(QWidget):
    """桌面字幕：无边框置顶小窗，显示当前朗读的句子，可用鼠标拖动。"""

    def __init__(self, cfg):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("桌面字幕")
        self.cfg = cfg
        self._drag = None
        self._width = 0
        self._is_placed = False
        self.lab = QLabel("")
        self.lab.setWordWrap(True)
        self.lab.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.lab)
        self.lab.hide()      # 没有朗读内容时不显示黑底
        self._apply_style()

    def _apply_style(self):
        size = int(self.cfg.get("subtitle_size", 22))
        self.lab.setStyleSheet(
            "QLabel { background: rgba(0,0,0,175); color: #ffffff;"
            f" border-radius: 12px; padding: 14px 22px; font-size: {size}px;"
            " font-family: 'Microsoft YaHei'; }")

    def set_text(self, text):
        self.lab.setText(text)
        self.lab.show()
        if not self._width:
            scr = QApplication.primaryScreen().availableGeometry()
            self._width = int(min(scr.width() * 0.7, max(520, 520)))
        self.lab.setFixedWidth(self._width)
        h = self.lab.heightForWidth(self._width)
        if h <= 0:
            h = self.lab.sizeHint().height()
        old_h = self.height() if self._is_placed else 0
        self.setFixedSize(self._width, h)
        if not self._is_placed:
            self._place_bottom_center()
            self._is_placed = True
        elif h != old_h:          # 增高时向上长，保持底边位置不变
            self.move(self.x(), self.y() - (h - old_h))

    def clear_text(self):
        """清空并隐藏文字（透明窗口仍在，避免残留黑底）。"""
        self.lab.clear()
        self.lab.hide()

    def _place_bottom_center(self):
        scr = QApplication.primaryScreen().availableGeometry()
        x = scr.x() + (scr.width() - self.width()) // 2
        y = scr.y() + scr.height() - self.height() - 80
        self.move(int(x), int(y))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class BackgroundTextEdit(QTextEdit):
    """支持背景图片 + 透明度的文本编辑器（背景固定在视口，不随滚动移动）。"""

    def __init__(self):
        super().__init__()
        self._bg = None
        self._opacity = 0.3
        self._base = QColor("#ffffff")
        self._spacing = 0

    def set_para_spacing(self, px: int):
        """段落间距（像素）：0=默认，正数加大段间距，负数压缩空行高度。"""
        self._spacing = max(-20, min(30, int(px)))
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            cur = QTextCursor(block)
            fmt = cur.blockFormat()
            fmt.setLineHeight(100, fmt.ProportionalHeight)  # 段内行高恢复默认
            if self._spacing >= 0:
                fmt.setBottomMargin(float(self._spacing))
            else:
                fmt.setBottomMargin(0.0)
                if not block.text().strip():  # 空行：按比例压缩其高度
                    pct = max(10, 100 + self._spacing * 5)
                    fmt.setLineHeight(pct, fmt.ProportionalHeight)
            cur.setBlockFormat(fmt)
            block = block.next()

    def setPlainText(self, text):
        super().setPlainText(text)
        self.set_para_spacing(self._spacing)  # 新文本块恢复默认格式，需重设

    def set_appearance(self, size: int, text_color: str, base_color: str):
        """字体大小 + 文字颜色 + 文档底色（背景图融合基色）。"""
        self.setFont(QFont("Microsoft YaHei", size))
        pal = self.palette()
        pal.setColor(QPalette.Text, QColor(text_color))
        self.setPalette(pal)
        self._base = QColor(base_color)
        self._refresh_bg()

    def set_background(self, path: str, opacity: float):
        self._bg = QPixmap(path) if path else None
        if self._bg is not None and self._bg.isNull():
            self._bg = None
        self._opacity = max(0.0, min(1.0, opacity))
        self._refresh_bg()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_bg()

    def _refresh_bg(self):
        vp = self.viewport()
        if self._bg is None or self._opacity <= 0 or vp.width() < 2:
            pal = vp.palette()
            pal.setColor(QPalette.Base, self._base)
            vp.setPalette(pal)
            vp.setAutoFillBackground(True)
            vp.update()
            return
        base = self._base
        img = QImage(vp.size(), QImage.Format_RGB32)
        img.fill(base)
        p = QPainter(img)
        p.setOpacity(self._opacity)
        scaled = self._bg.scaled(vp.size(), Qt.KeepAspectRatioByExpanding,
                                 Qt.SmoothTransformation)
        p.drawPixmap(0, 0, scaled)
        p.end()
        pal = vp.palette()
        pal.setBrush(QPalette.Base, QBrush(QPixmap.fromImage(img)))
        vp.setPalette(pal)
        vp.setAutoFillBackground(True)


class MainWindow(QMainWindow):
    _export_progress = pyqtSignal(int)   # 子线程 → 主线程 更新进度（跨线程改控件会崩）

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TXT 朗读器 1.0（百度语音）")
        self.resize(980, 620)
        self.setAcceptDrops(True)

        self.cfg = config.load()
        self.tts = BaiduTTS(self.cfg["api_key"], self.cfg["secret_key"])
        self.player = Player(self.tts)
        self.chunks = []          # 当前文本分段 [(s,e,text)]
        self._state = "stopped"
        self._cur_path = ""       # 当前载入的 txt 路径（列表循环用）
        self._cur_idx = -1        # 当前朗读段序号（字幕用）
        self.subtitle = SubtitleWindow(self.cfg)   # 桌面字幕小窗（默认隐藏）

        self._build_ui()
        self._build_menu()
        self._connect_player()
        self.editor.setPlainText(WELCOME)
        self.editor.set_para_spacing(config.get_spacing(self.cfg))
        _cur = self.editor.textCursor()
        _cur.setPosition(0)
        self.editor.setTextCursor(_cur)

        # 悬浮朗读列表窗口
        self.playlist_win = PlaylistWindow(self)
        self.playlist = self.playlist_win.list
        # 恢复上次的朗读列表（跳过已被删除的文件）
        for p in self.cfg.get("playlist") or []:
            if isinstance(p, str) and os.path.exists(p):
                self._add_to_list(p, persist=False)
        if len(self.cfg.get("playlist") or []) != self.playlist.count():
            self._save_playlist()

        # 恢复上次的背景 / 伴音设置
        self.editor.set_background(self.cfg["bg_path"],
                                   int(self.cfg["bg_opacity"]) / 100.0)
        self.player.set_bgm(self.cfg["bgm_path"],
                            int(self.cfg["bgm_vol"]) / 100.0,
                            bool(self.cfg["bgm_on"]))

        if not self.tts.configured():
            self.statusBar().showMessage("尚未配置百度 API Key，请点击 选项 → 百度语音设置")

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.editor = BackgroundTextEdit()
        self.editor.set_appearance(int(self.cfg["font_size"]),
                                   self.cfg["text_color"], self.cfg["doc_bg"])
        root.addWidget(self.editor, 1)

        # ---- 朗读进度条（仿 PotPlayer 细黄线，可拖动跳转）----
        row_seek = QHBoxLayout()
        row_seek.setContentsMargins(6, 0, 6, 0)
        self.slider_progress = SeekSlider(Qt.Horizontal)
        self.slider_progress.setRange(0, 0)
        self.slider_progress.setFixedHeight(16)
        self.slider_progress.setToolTip("拖动或点击黄线，可任意跳转朗读进度")
        self.slider_progress.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal { height: 3px; background: #6b5a12; border-radius: 1px; }
            QSlider::sub-page:horizontal { height: 3px; background: #ffd400; border-radius: 1px; }
            QSlider::add-page:horizontal { height: 3px; background: #6b5a12; border-radius: 1px; }
            QSlider::handle:horizontal {
                width: 12px; height: 12px; margin: -5px 0;
                border-radius: 6px; background: #ffffff; border: 2px solid #ffd400;
            }
        """)
        self.slider_progress.seek_requested.connect(self._on_seek)
        row_seek.addWidget(self.slider_progress, 1)
        self.lab_progress = QLabel("0 / 0 句")
        self.lab_progress.setFixedWidth(80)
        self.lab_progress.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row_seek.addWidget(self.lab_progress)
        root.addLayout(row_seek)

        # ---- 播放控制行 ----
        row1 = QHBoxLayout()
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(90)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_prev = QPushButton("⏮ 上一段")
        self.btn_prev.clicked.connect(lambda: self.player.skip(-1))
        self.btn_next = QPushButton("⏭ 下一段")
        self.btn_next.clicked.connect(lambda: self.player.skip(1))
        row1.addWidget(self.btn_play)
        row1.addWidget(self.btn_stop)
        row1.addWidget(self.btn_prev)
        row1.addWidget(self.btn_next)
        row1.addSpacing(20)
        row1.addWidget(QLabel("朗读模式：朗读"))
        self.spin_rounds = QSpinBox()
        self.spin_rounds.setRange(1, 99)
        self.spin_rounds.setValue(int(self.cfg["rounds"]))
        row1.addWidget(self.spin_rounds)
        row1.addWidget(QLabel("次"))
        row1.addSpacing(16)
        row1.addWidget(QLabel("循环："))
        self.cb_loop = QComboBox()
        self.cb_loop.addItem("读完停止", 0)
        self.cb_loop.addItem("单文件循环", 1)
        self.cb_loop.addItem("列表循环", 2)
        self.cb_loop.setCurrentIndex(max(0, int(self.cfg.get("loop_mode", 0))))
        self.cb_loop.setToolTip("单文件循环：读完后重读当前文件\n列表循环：读完后自动读朗读列表的下一本")
        row1.addWidget(self.cb_loop)
        row1.addSpacing(20)
        btn_export = QPushButton("♫ 生成声音文件")
        btn_export.clicked.connect(self.export_mp3)
        row1.addWidget(btn_export)
        btn_list = QPushButton("📋 朗读列表")
        btn_list.clicked.connect(self._toggle_playlist)
        row1.addWidget(btn_list)
        row1.addStretch(1)
        root.addLayout(row1)

        # ---- 发音人 / 参数行 ----
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("发音人："))
        self.cb_voice = QComboBox()
        for per, name in VOICES:
            self.cb_voice.addItem(name, per)
        idx = self.cb_voice.findData(self.cfg["per"])
        self.cb_voice.setCurrentIndex(max(0, idx))
        row2.addWidget(self.cb_voice)

        self.sliders = {}
        for key, label in (("spd", "语速"), ("vol", "音量"), ("pit", "语调")):
            row2.addSpacing(12)
            row2.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            if key == "spd":  # 语速：0=正常，负值减速，正值加速；映射到百度 0-15
                s.setRange(-5, 10)
                s.setValue(int(self.cfg[key]) - 5)
                s.setToolTip("0=正常，负数减速，正数加速")
            else:
                s.setRange(0, 15)
                s.setValue(int(self.cfg[key]))
            s.setFixedWidth(110)
            lab = QLabel(str(s.value()))
            lab.setFixedWidth(20)
            s.valueChanged.connect(lambda v, l=lab: l.setText(str(v)))
            row2.addWidget(s)
            row2.addWidget(lab)
            self.sliders[key] = s
        row2.addStretch(1)
        root.addLayout(row2)

        # 参数变更即保存
        self.cb_voice.currentIndexChanged.connect(self._save_voice_cfg)
        for s in self.sliders.values():
            s.valueChanged.connect(self._save_voice_cfg)
        self.spin_rounds.valueChanged.connect(self._save_voice_cfg)
        self.cb_loop.currentIndexChanged.connect(self._save_voice_cfg)

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("文件(&F)")
        self._add_action(m_file, "新建/清空", self._new_doc, "Ctrl+N")
        self._add_action(m_file, "打开 TXT…", self._open_file, "Ctrl+O")
        self._add_action(m_file, "保存文本…", self._save_text, "Ctrl+S")
        m_file.addSeparator()
        self._add_action(m_file, "生成声音文件(MP3)…", self.export_mp3)
        m_file.addSeparator()
        self._add_action(m_file, "退出", self.close)

        m_read = mb.addMenu("朗读(&R)")
        self._add_action(m_read, "播放 / 暂停", self.toggle_play, "F5")
        self._add_action(m_read, "停止", self.stop, "F6")
        self._add_action(m_read, "上一段", lambda: self.player.skip(-1), "F7")
        self._add_action(m_read, "下一段", lambda: self.player.skip(1), "F8")
        m_read.addSeparator()
        a_sub = QAction("桌面字幕", self)
        a_sub.setCheckable(True)
        a_sub.setShortcut("F9")
        a_sub.setChecked(bool(self.cfg.get("subtitle_on")))
        a_sub.toggled.connect(self._toggle_subtitle)
        m_read.addAction(a_sub)

        m_opt = mb.addMenu("选项(&O)")
        self._add_action(m_opt, "百度语音设置…", self.open_settings)

        m_prefs = mb.addMenu("设置(&S)")
        self._add_action(m_prefs, "伴音与背景设置…", self.open_prefs)

        m_help = mb.addMenu("帮助(&H)")
        self._add_action(m_help, "使用说明", self._show_help)

    def _add_action(self, menu, text, fn, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def _connect_player(self):
        self.player.chunk_started.connect(self._on_chunk)
        self.player.state_changed.connect(self._on_state)
        self.player.status_text.connect(self.statusBar().showMessage)
        self.player.error.connect(self._on_error)
        self.player.round_changed.connect(
            lambda r, n: self.statusBar().showMessage(f"第 {r}/{n} 遍"))

    # ---------------- 配置 ----------------
    def _save_voice_cfg(self):
        self.cfg["per"] = self.cb_voice.currentData()
        for k, s in self.sliders.items():
            self.cfg[k] = s.value() + 5 if k == "spd" else s.value()
        self.cfg["rounds"] = self.spin_rounds.value()
        self.cfg["loop_mode"] = self.cb_loop.currentData()
        config.save(self.cfg)

    # ---------------- 设置 / 朗读列表 ----------------
    def open_prefs(self):
        dlg = PrefsDialog(self.cfg, self.player, self.editor, self)
        dlg.exec_()

    def _toggle_playlist(self):
        if self.playlist_win.isVisible():
            self.playlist_win.hide()
        else:
            g = self.geometry()
            self.playlist_win.move(g.right() - 340, g.top() + 60)
            self.playlist_win.show()
            self.playlist_win.raise_()

    def _voice_params(self):
        return {"per": self.cb_voice.currentData(),
                "spd": self.sliders["spd"].value() + 5,  # -5~10 → 0~15
                "pit": self.sliders["pit"].value(),
                "vol": self.sliders["vol"].value()}

    # ---------------- 文件 ----------------
    def _new_doc(self):
        self.stop()
        self.editor.clear()
        self._reset_progress()

    def _reset_progress(self):
        """新文本载入后清空进度条。"""
        self.chunks = []
        self._cur_idx = -1
        self.slider_progress.setRange(0, 0)
        self.slider_progress.setValue(0)
        self.lab_progress.setText("0 / 0 句")
        self.editor.setExtraSelections([])

    def _on_seek(self, value):
        """进度条跳转：播放中直接跳段，未播放时把光标移到该句。"""
        if not self.chunks:
            return
        idx = max(0, min(len(self.chunks) - 1, int(value)))
        if self._state in ("playing", "paused"):
            self.player.seek(idx)
        self._on_chunk(idx, len(self.chunks))

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开 TXT", "", "文本文件 (*.txt)")
        if path:
            self._load_path(path)

    def _load_path(self, path):
        try:
            for enc in ("utf-8", "gbk"):
                try:
                    with open(path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("无法识别文件编码")
            self.stop()
            self.editor.setPlainText(text)
            cur = self.editor.textCursor()
            cur.setPosition(0)            # 新文件从第一句开始读
            self.editor.setTextCursor(cur)
            self._cur_path = path
            self.chunks = split_text(text)
            self.slider_progress.setRange(0, max(0, len(self.chunks) - 1))
            self.slider_progress.setValue(0)
            self.lab_progress.setText(f"0 / {len(self.chunks)} 句")
            self._cur_idx = -1
            self.setWindowTitle(f"TXT 朗读器 1.0 [ {os.path.basename(path)} ]")
            self._add_to_list(path)
            self.statusBar().showMessage(f"已载入：{path}（{len(text)} 字）")
        except OSError as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def _save_text(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存文本", "", "文本文件 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加到朗读列表", "", "文本文件 (*.txt)")
        for p in paths:
            self._add_to_list(p)

    def _add_to_list(self, path, persist=True):
        for i in range(self.playlist.count()):
            if self.playlist.item(i).data(Qt.UserRole) == path:
                return
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.playlist.addItem(item)
        if persist:
            self._save_playlist()

    def _del_file(self):
        for item in self.playlist.selectedItems():
            self.playlist.takeItem(self.playlist.row(item))
        self._save_playlist()

    def _clear_playlist(self):
        self.playlist.clear()
        self._save_playlist()

    def _save_playlist(self):
        """朗读列表持久化，下次启动自动恢复。"""
        self.cfg["playlist"] = [self.playlist.item(i).data(Qt.UserRole)
                                for i in range(self.playlist.count())]
        config.save(self.cfg)

    def _load_item(self, item):
        self._load_path(item.data(Qt.UserRole))

    # ---------------- 播放 ----------------
    def toggle_play(self):
        if self._state == "playing":
            self.player.pause()
            return
        if self._state == "paused":
            self.player.resume()
            return
        self.start()

    def start(self, from_begin=False):
        if not self.tts.configured():
            r = QMessageBox.question(self, "未配置 API Key",
                                     "需要先配置百度 API Key / Secret Key 才能朗读。\n现在打开设置吗？")
            if r == QMessageBox.Yes:
                self.open_settings()
            return
        text = self.editor.toPlainText()
        self.chunks = split_text(text)
        if not self.chunks:
            self.statusBar().showMessage("没有可朗读的文字")
            return
        # 从光标所在段开始（循环重读从头开始）
        if from_begin:
            start = 0
            cur = self.editor.textCursor()
            cur.setPosition(0)
            self.editor.setTextCursor(cur)
        else:
            pos = self.editor.textCursor().position()
            start = 0
            for i, (s, e, _) in enumerate(self.chunks):
                if s <= pos < e:
                    start = i
                    break
                if pos >= e:
                    start = i
        self.slider_progress.setRange(0, max(0, len(self.chunks) - 1))
        self.slider_progress.setValue(start)
        self.lab_progress.setText(f"{start + 1} / {len(self.chunks)} 句")
        self.player.play(self.chunks, self._voice_params(), start,
                         self.spin_rounds.value())

    def stop(self):
        self.player.stop(join=True)
        self._on_state("stopped")
        self.statusBar().showMessage("已停止")

    def _on_state(self, state):
        self._state = state
        if state == "playing":
            self.btn_play.setText("⏸ 暂停")
        elif state == "paused":
            self.btn_play.setText("▶ 继续")
        else:
            self.btn_play.setText("▶ 播放")
            if state in ("finished", "stopped"):
                self.editor.setExtraSelections([])
                self.subtitle.clear_text()
        if state == "finished":
            QTimer.singleShot(0, self._after_finished)

    def _after_finished(self):
        """一遍读完（含设定遍数）后，按循环模式决定是否续读。"""
        mode = self.cb_loop.currentData()
        if mode == 1:            # 单文件循环：从头重读当前文件
            self.start(from_begin=True)
        elif mode == 2:          # 列表循环：读列表里的下一本
            n = self.playlist.count()
            if n == 0:
                return
            cur = -1
            for i in range(n):
                if self.playlist.item(i).data(Qt.UserRole) == self._cur_path:
                    cur = i
                    break
            self._load_item(self.playlist.item((cur + 1) % n))
            self.start()

    def _toggle_subtitle(self, checked):
        self.cfg["subtitle_on"] = bool(checked)
        config.save(self.cfg)
        if self.cfg.get("subtitle_on"):
            if 0 <= self._cur_idx < len(self.chunks):
                self.subtitle.set_text(self.chunks[self._cur_idx][2].strip())
            else:
                self.subtitle.set_text("桌面字幕已开启，开始朗读后显示当前句子")
            self.subtitle.show()
            self.subtitle.raise_()
        else:
            self.subtitle.hide()

    def _on_chunk(self, idx, total):
        if idx >= len(self.chunks):
            return
        self._cur_idx = idx
        s, e, text = self.chunks[idx]
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(self.cfg.get("hl_color", "#fff3a0")))
        cur = self.editor.textCursor()
        cur.setPosition(s)
        cur.setPosition(e, QTextCursor.KeepAnchor)
        sel.cursor = cur
        self.editor.setExtraSelections([sel])
        c2 = self.editor.textCursor()
        c2.setPosition(s)
        self.editor.setTextCursor(c2)  # 滚动到可见
        if not self.slider_progress.isSliderDown():
            self.slider_progress.setValue(idx)
        self.lab_progress.setText(f"{idx + 1} / {len(self.chunks)} 句")
        if self.cfg.get("subtitle_on"):
            if not self.subtitle.isVisible():
                self.subtitle.show()
            self.subtitle.set_text(text.strip())

    def _on_error(self, msg):
        self._on_state("stopped")
        QMessageBox.warning(self, "朗读出错", msg)

    # ---------------- 导出 ----------------
    def export_mp3(self):
        if not self.tts.configured():
            self.open_settings()
            return
        text = self.editor.toPlainText()
        chunks = split_text(text)
        if not chunks:
            return
        path, _ = QFileDialog.getSaveFileName(self, "生成声音文件", "朗读.mp3", "MP3 文件 (*.mp3)")
        if not path:
            return
        prog = QProgressDialog("正在生成声音文件…", "取消", 0, len(chunks), self)
        prog.setWindowTitle("生成 MP3")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        cancelled = threading.Event()
        self._export_progress.connect(prog.setValue)

        def work():
            try:
                self.player.export_mp3(chunks, self._voice_params(), path,
                                       lambda i, n: self._export_progress.emit(i))
                self._export_progress.emit(len(chunks))
            except Exception as e:
                if not cancelled.is_set():
                    self.player.error.emit(str(e))

        t = threading.Thread(target=work, daemon=True)
        t.start()
        prog.canceled.connect(cancelled.set)

    # ---------------- 其他 ----------------
    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self.tts, self)
        if dlg.exec_():
            config.save(self.cfg)
            self.tts.api_key = self.cfg["api_key"]
            self.tts.secret_key = self.cfg["secret_key"]
            self.tts._token = None
            self.statusBar().showMessage("设置已保存")

    def _show_help(self):
        QMessageBox.information(self, "使用说明", WELCOME)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".txt"):
                self._load_path(p)

    def closeEvent(self, e):
        self.player.stop()
        self.playlist_win.hide()
        self.subtitle.close()
        self._save_voice_cfg()
        super().closeEvent(e)
