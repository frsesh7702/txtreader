"""偏好设置对话框：伴音 + 阅读区背景 + 外观（字体/颜色）。"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFileDialog,
                             QGroupBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QSlider, QSpinBox,
                             QVBoxLayout)

import config


class PrefsDialog(QDialog):
    def __init__(self, cfg, player, editor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self.cfg = cfg
        self.player = player
        self.editor = editor

        lay = QVBoxLayout(self)

        # ---- 伴音 ----
        g_bgm = QGroupBox("伴音（背景音乐，最多 5 首备用）")
        vb = QVBoxLayout(g_bgm)
        row = QHBoxLayout()
        self.chk_bgm = QCheckBox("启用伴音")
        self.chk_bgm.setChecked(bool(cfg["bgm_on"]))
        row.addWidget(self.chk_bgm)
        row.addStretch(1)
        vb.addLayout(row)
        # 备用音乐列表
        self.lst_bgm = QListWidget()
        self.lst_bgm.setMaximumHeight(120)
        self.lst_bgm.itemClicked.connect(self._bgm_item_clicked)
        self._reload_bgm_list()
        vb.addWidget(self.lst_bgm)
        row = QHBoxLayout()
        btn_add = QPushButton("+ 添加音乐")
        btn_add.clicked.connect(self._add_bgm)
        row.addWidget(btn_add)
        btn_del = QPushButton("− 删除选中")
        btn_del.clicked.connect(self._del_bgm)
        row.addWidget(btn_del)
        btn_clear = QPushButton("清空列表")
        btn_clear.clicked.connect(self._clear_bgm)
        row.addWidget(btn_clear)
        row.addStretch(1)
        vb.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("伴音音量"))
        self.sl_bgm = QSlider(Qt.Horizontal)
        self.sl_bgm.setRange(0, 100)
        self.sl_bgm.setValue(int(cfg["bgm_vol"]))
        self.lab_bgm_vol = QLabel(str(self.sl_bgm.value()))
        self.lab_bgm_vol.setFixedWidth(40)
        row.addWidget(self.sl_bgm, 1)
        row.addWidget(self.lab_bgm_vol)
        vb.addLayout(row)
        lay.addWidget(g_bgm)

        # ---- 背景 ----
        g_bg = QGroupBox("阅读区背景")
        vg = QVBoxLayout(g_bg)
        row = QHBoxLayout()
        btn = QPushButton("选择图片…")
        btn.clicked.connect(self._pick_bg)
        row.addWidget(btn)
        self.lab_bg = QLabel(os.path.basename(cfg["bg_path"]) or "（未设置）")
        self.lab_bg.setToolTip(cfg["bg_path"])
        row.addWidget(self.lab_bg, 1)
        btn = QPushButton("清除")
        btn.clicked.connect(self._clear_bg)
        row.addWidget(btn)
        vg.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("透明度"))
        self.sl_bg = QSlider(Qt.Horizontal)
        self.sl_bg.setRange(0, 100)
        self.sl_bg.setValue(int(cfg["bg_opacity"]))
        self.lab_bg_op = QLabel(f"{self.sl_bg.value()}%")
        self.sl_bg.valueChanged.connect(lambda v: self.lab_bg_op.setText(f"{v}%"))
        row.addWidget(self.sl_bg, 1)
        row.addWidget(self.lab_bg_op)
        vg.addLayout(row)
        lay.addWidget(g_bg)

        # ---- 外观（字体/颜色）----
        g_font = QGroupBox("外观")
        vf = QVBoxLayout(g_font)
        row = QHBoxLayout()
        row.addWidget(QLabel("字体大小"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(8, 36)
        self.spin_font.setValue(int(cfg["font_size"]))
        row.addWidget(self.spin_font)
        row.addSpacing(12)
        self.btn_text_color = self._color_btn("字体颜色", "text_color")
        row.addWidget(self.btn_text_color)
        row.addStretch(1)
        vf.addLayout(row)
        row = QHBoxLayout()
        self.btn_hl = self._color_btn("朗读句背景色", "hl_color")
        row.addWidget(self.btn_hl)
        self.btn_docbg = self._color_btn("文档背景色", "doc_bg")
        row.addWidget(self.btn_docbg)
        row.addStretch(1)
        vf.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("段落间距"))
        self.sl_spacing = QSlider(Qt.Horizontal)
        self.sl_spacing.setRange(-20, 30)
        self.sl_spacing.setValue(config.get_spacing(cfg))
        self.sl_spacing.setToolTip("0 默认，正数加大段落间距，负数压缩空行高度")
        self.lab_spacing = QLabel(f"{self.sl_spacing.value():+d} px")
        self.lab_spacing.setFixedWidth(48)
        self.sl_spacing.valueChanged.connect(
            lambda v: self.lab_spacing.setText(f"{v:+d} px"))
        self.sl_spacing.valueChanged.connect(self._apply_spacing)
        row.addWidget(self.sl_spacing, 1)
        row.addWidget(self.lab_spacing)
        vf.addLayout(row)
        lay.addWidget(g_font)

        self.spin_font.valueChanged.connect(self._apply_font)

        btn = QPushButton("关闭")
        btn.clicked.connect(self.close)
        lay.addWidget(btn, alignment=Qt.AlignRight)

        # 实时生效
        self.chk_bgm.toggled.connect(self._apply_bgm)
        self.sl_bgm.valueChanged.connect(self._bgm_vol_live)      # 拖动中只调音量，不写盘
        self.sl_bgm.sliderReleased.connect(self._apply_bgm)        # 松手再保存
        self.sl_bgm.sliderMoved.connect(lambda v: self.lab_bgm_vol.setText(str(v)))
        self.sl_bgm.sliderPressed.connect(lambda: self.lab_bgm_vol.setText(str(self.sl_bgm.value())))
        self.sl_bg.valueChanged.connect(self._apply_bg)

    # ---- 伴音 ----
    def _bgm_vol_live(self, v: int):
        """拖动滑杆中只轻量调音量，不写盘、不处理开关。"""
        self.player.set_bgm_volume(v / 100.0)

    def _reload_bgm_list(self):
        """根据 cfg 重建列表，并恢复选中状态。"""
        self.lst_bgm.clear()
        lst = self.cfg.get("bgm_list", [])[:5]
        sel = self.cfg.get("bgm_index", -1)
        for i, p in enumerate(lst):
            item = QListWidgetItem(f"▶ {os.path.basename(p)}" if i == sel else f"  {os.path.basename(p)}")
            item.setToolTip(p)
            self.lst_bgm.addItem(item)
            if i == sel:
                item.setSelected(True)
                self.lst_bgm.setCurrentRow(i)

    def _add_bgm(self):
        cur = self.cfg.get("bgm_list", [])[:5]
        if len(cur) >= 5:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "最多只能添加 5 首备用音乐")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择伴音音乐", "",
                                              "音乐文件 (*.mp3 *.wav *.ogg)")
        if not path:
            return
        if path in cur:
            # 已存在则直接选中
            self.cfg["bgm_index"] = cur.index(path)
        else:
            cur.append(path)
            self.cfg["bgm_list"] = cur
            self.cfg["bgm_index"] = len(cur) - 1
        self.cfg["bgm_path"] = cur[self.cfg["bgm_index"]]
        self._reload_bgm_list()
        self._apply_bgm()

    def _del_bgm(self):
        row = self.lst_bgm.currentRow()
        lst = self.cfg.get("bgm_list", [])[:5]
        if row < 0 or row >= len(lst):
            return
        del lst[row]
        self.cfg["bgm_list"] = lst
        # 选中修复
        sel = self.cfg.get("bgm_index", -1)
        if row == sel:
            if lst:
                self.cfg["bgm_index"] = min(row, len(lst) - 1)
            else:
                self.cfg["bgm_index"] = -1
        elif row < sel:
            self.cfg["bgm_index"] = sel - 1
        self.cfg["bgm_path"] = lst[self.cfg["bgm_index"]] if self.cfg["bgm_index"] >= 0 else ""
        self._reload_bgm_list()
        self._apply_bgm()

    def _clear_bgm(self):
        self.cfg["bgm_list"] = []
        self.cfg["bgm_index"] = -1
        self.cfg["bgm_path"] = ""
        self._reload_bgm_list()
        self._apply_bgm()

    def _bgm_item_clicked(self, item):
        row = self.lst_bgm.row(item)
        lst = self.cfg.get("bgm_list", [])[:5]
        if 0 <= row < len(lst):
            self.cfg["bgm_index"] = row
            self.cfg["bgm_path"] = lst[row]
            self._reload_bgm_list()
            self._apply_bgm()

    def _apply_bgm(self):
        self.cfg["bgm_on"] = self.chk_bgm.isChecked()
        self.cfg["bgm_vol"] = self.sl_bgm.value()
        config.save(self.cfg)
        self.player.set_bgm(self.cfg.get("bgm_path", ""),
                            self.sl_bgm.value() / 100.0,
                            self.chk_bgm.isChecked())

    # ---- 外观 ----
    @staticmethod
    def _swatch_style(hex_color):
        c = QColor(hex_color)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        fg = "#000000" if lum > 140 else "#ffffff"
        return f"background-color: {hex_color}; color: {fg}; padding: 2px 10px;"

    def _color_btn(self, label, key):
        b = QPushButton(f"{label} {self.cfg[key]}")
        b.setStyleSheet(self._swatch_style(self.cfg[key]))
        b.clicked.connect(lambda: self._pick_color(key, label, b))
        return b

    def _pick_color(self, key, label, btn):
        c = QColorDialog.getColor(QColor(self.cfg[key]), self, f"选择{label}")
        if c.isValid():
            self.cfg[key] = c.name()
            btn.setText(f"{label} {c.name()}")
            btn.setStyleSheet(self._swatch_style(c.name()))
            config.save(self.cfg)
            self._apply_font()

    def _apply_font(self):
        self.cfg["font_size"] = self.spin_font.value()
        config.save(self.cfg)
        self.editor.set_appearance(self.spin_font.value(),
                                   self.cfg["text_color"], self.cfg["doc_bg"])

    def _apply_spacing(self):
        self.cfg["para_spacing"] = self.sl_spacing.value()
        config.save(self.cfg)
        self.editor.set_para_spacing(self.sl_spacing.value())

    # ---- 背景 ----
    def _pick_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.cfg["bg_path"] = path
            self.lab_bg.setText(os.path.basename(path))
            self.lab_bg.setToolTip(path)
            self._apply_bg()

    def _clear_bg(self):
        self.cfg["bg_path"] = ""
        self.lab_bg.setText("（未设置）")
        self.lab_bg.setToolTip("")
        self._apply_bg()

    def _apply_bg(self):
        self.cfg["bg_opacity"] = self.sl_bg.value()
        config.save(self.cfg)
        self.editor.set_background(self.cfg["bg_path"], self.sl_bg.value() / 100.0)
