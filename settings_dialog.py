"""百度语音 API Key 设置对话框。"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

HELP = """\
<b>如何申请百度免费语音 Key（约 5 分钟）：</b>
<ol>
<li>打开 <a href="https://console.bce.baidu.com/ai/#/ai/speech/overview/index">百度智能云 · 语音技术控制台</a>，用百度账号登录并完成实名认证。</li>
<li>在「语音合成」中点击 <b>创建应用</b>（接口勾选语音合成，归属个人即可）。</li>
<li>创建后在应用列表中即可看到 <b>API Key</b> 和 <b>Secret Key</b>，复制到下面。</li>
<li>在「语音合成」页面领取 <b>免费调用额度</b>（基础、精品、臻品三个音库各有独立免费额度，建议都领取）。</li>
</ol>
"""


class SettingsDialog(QDialog):
    def __init__(self, cfg, tts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("百度语音设置")
        self.setMinimumWidth(520)
        self.cfg = cfg
        self.tts = tts

        lay = QVBoxLayout(self)
        tip = QLabel(HELP)
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.RichText)
        tip.setOpenExternalLinks(True)
        lay.addWidget(tip)

        form = QFormLayout()
        self.ed_key = QLineEdit(cfg.get("api_key", ""))
        self.ed_secret = QLineEdit(cfg.get("secret_key", ""))
        self.ed_secret.setEchoMode(QLineEdit.Password)
        form.addRow("API Key：", self.ed_key)
        form.addRow("Secret Key：", self.ed_secret)
        lay.addLayout(form)

        btns = QHBoxLayout()
        btn_open = QPushButton("打开申请页面")
        btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://console.bce.baidu.com/ai/#/ai/speech/overview/index")))
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test)
        btn_save = QPushButton("保存")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        for b in (btn_open, btn_test, btn_save, btn_cancel):
            btns.addWidget(b)
        lay.addLayout(btns)

    def _save(self):
        self.cfg["api_key"] = self.ed_key.text().strip()
        self.cfg["secret_key"] = self.ed_secret.text().strip()
        self.accept()

    def _test(self):
        self.tts.api_key = self.ed_key.text().strip()
        self.tts.secret_key = self.ed_secret.text().strip()
        self.tts._token = None
        try:
            self.tts.get_token(force=True)
            QMessageBox.information(self, "测试连接", "连接成功，Key 有效！")
        except Exception as e:
            QMessageBox.warning(self, "测试连接", f"连接失败：\n{e}")
