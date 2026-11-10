"""百度智能云 · 语音合成（TTS）短文本在线合成 API 客户端。

文档: https://ai.baidu.com/ai-doc/SPEECH/7k38y5e5p
免费额度: 实名认证后基础音库有免费调用额度。
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
TTS_URL = "https://tsn.baidu.com/text2audio"

# 走 curl.exe（Windows 原生 Schannel TLS）。
# 不使用 requests：部分机器的 Python OpenSSL 在 TLS 握手时会发生访问冲突（进程直接崩溃）。
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _find_curl():
    p = shutil.which("curl")
    if p:
        return p
    for cand in (r"C:\Windows\System32\curl.exe", r"C:\Windows\SysWOW64\curl.exe"):
        if os.path.exists(cand):
            return cand
    return None


_CURL = _find_curl()

# 发音人 (per 参数)。基础/精品/臻品音库均有免费额度，需在控制台分别领取。
VOICES = [
    # ---- 基础音库 ----
    (0, "度小美·标准女声"),
    (1, "度小宇·亲切男声"),
    (3, "度逍遥·情感男声"),
    (4, "度丫丫·童声"),
    # ---- 精品音库 ----
    (5003, "度逍遥·情感男声【精品】"),
    (5118, "度小鹿·甜美女声【精品】"),
    (5, "度小娇·成熟女主播【精品】"),
    (103, "度米朵·可爱童声【精品】"),
    (106, "度博文·专业男主播【精品】"),
    (110, "度小童·童声主播【精品】"),
    (111, "度小萌·软萌妹子【精品】"),
    # ---- 臻品音库（音质最好，需领取臻品免费额度）----
    (4003, "度逍遥·情感男声【臻品】"),
    (4106, "度博文·专业男主播【臻品】"),
    (4115, "度小贤·电台男主播【臻品】"),
    (4119, "度小鹿·甜美女声【臻品】"),
    (4105, "度灵儿·清澈女声【臻品】"),
    (4117, "度小乔·活泼女声【臻品】"),
    (4100, "度小雯·活力女主播【臻品】"),
    (4103, "度米朵·可爱女声【臻品】"),
    (4144, "度姗姗·娱乐女声【臻品】"),
    (4278, "度小贝·知识女主播【臻品】"),
    (4143, "度清风·配音男声【臻品】"),
]

# 错误码 -> 含义
ERRORS = {
    500: "不支持的输入",
    501: "输入参数不正确",
    502: "token 验证失败（请检查 API Key / Secret Key）",
    503: "合成后端错误（臻品/精品音色需先在控制台领取对应音库免费额度，或换基础音色）",
}


class TTSError(Exception):
    pass


def _run_curl(args, timeout: int, stdin_bytes: bytes = None) -> bytes:
    """执行 curl，返回 stdout 字节。失败抛 TTSError。"""
    if not _CURL:
        raise TTSError("未找到 curl.exe（Windows 10 及以上系统自带），无法联网合成")
    cmd = [_CURL, "-sS", "--connect-timeout", "10", "--max-time", str(timeout)] + args
    try:
        p = subprocess.run(cmd, input=stdin_bytes, capture_output=True,
                           timeout=timeout + 15, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise TTSError("网络请求超时，请检查网络连接")
    except OSError as e:
        raise TTSError(f"无法执行 curl: {e}")
    if p.returncode != 0:
        detail = p.stderr.decode("utf-8", "ignore").strip()[:200]
        raise TTSError(f"网络请求失败: {detail}")
    return p.stdout


class BaiduTTS:
    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key.strip()
        self.secret_key = secret_key.strip()
        self._token = None
        self._token_expire = 0.0

    def configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    # ---------------- token ----------------
    def get_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expire - 300:
            return self._token
        if not self.configured():
            raise TTSError("尚未配置 API Key / Secret Key，请先在 选项 → 百度语音设置 中填写")
        query = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        })
        raw = _run_curl([f"{TOKEN_URL}?{query}"], 15)
        try:
            data = json.loads(raw.decode("utf-8", "ignore"))
        except ValueError:
            raise TTSError("获取 token 返回异常，请检查网络")
        if "access_token" not in data:
            raise TTSError(f"获取 token 失败: {data.get('error_description', data)}")
        self._token = data["access_token"]
        self._token_expire = time.time() + int(data.get("expires_in", 2592000))
        return self._token

    # ---------------- 合成 ----------------
    def synth(self, text: str, per: int = 0, spd: int = 5, pit: int = 5,
              vol: int = 5, retry: int = 1) -> bytes:
        """合成一段文本，返回 mp3 字节。spd/pit/vol 范围 0-15。"""
        if not text.strip():
            raise TTSError("合成文本为空")
        last_err = None
        for attempt in range(retry + 1):
            token = self.get_token(force=attempt > 0)
            params = {
                "tex": text,
                "tok": token,
                "cuid": "txt_reader_app",
                "ctp": 1,
                "lan": "zh",
                "spd": max(0, min(15, spd)),
                "pit": max(0, min(15, pit)),
                "vol": max(0, min(15, vol)),
                "per": per,
                "aue": 3,  # mp3
            }
            body = urllib.parse.urlencode(params).encode("utf-8")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tts")
            tmp.close()
            try:
                meta = _run_curl([
                    "-X", "POST",
                    "-H", "Content-Type: application/x-www-form-urlencoded",
                    "--data-binary", "@-",
                    "-o", tmp.name,
                    "-w", "%{http_code}\t%{content_type}",
                    TTS_URL,
                ], 30, stdin_bytes=body)
                with open(tmp.name, "rb") as f:
                    content = f.read()
            except TTSError as e:
                last_err = e
                continue
            except OSError:
                raise TTSError("无法写入临时文件")
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
            ctype = meta.decode("utf-8", "ignore").split("\t")[-1]
            if "audio" in ctype:
                return content
            try:
                err = json.loads(content.decode("utf-8", "ignore"))
                code = err.get("err_no")
                msg = ERRORS.get(code, err.get("err_msg", "未知错误"))
                last_err = TTSError(f"合成失败 [{code}]: {msg}")
                if code == 502:  # token 失效，重试会强制刷新
                    continue
                break
            except ValueError:
                last_err = TTSError(f"合成返回异常: {content[:200]!r}")
                break
        raise last_err or TTSError("合成失败")


def split_text(text: str, max_bytes: int = 900):
    """把长文本切成句子级小段，并保留每段在原串中的偏移。

    每个句子单独成段（用于朗读时逐句高亮）；单句超 max_bytes (UTF-8) 时硬切。
    返回 [(start, end, chunk_text), ...]
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    import re
    pieces = re.split(r"(?<=[。！？!?.…;；\n])", text)
    chunks = []
    pos = 0
    for piece in pieces:
        if not piece:
            continue
        start = pos
        pos += len(piece)
        # 单句超长：按字节硬切
        while len(piece.encode("utf-8")) > max_bytes:
            cut = len(piece)
            while len(piece[:cut].encode("utf-8")) > max_bytes:
                cut -= 1
            chunks.append((start, start + cut, piece[:cut]))
            start += cut
            piece = piece[cut:]
        if piece.strip():
            chunks.append((start, start + len(piece), piece))
    return chunks
