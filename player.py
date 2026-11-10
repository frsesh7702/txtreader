"""朗读播放控制器：分句合成（预取）+ pygame 顺序播放。

线程模型：
- synth 线程：始终保持当前播放位置前方 PREFETCH 段已合成，写入缓存。
- play  线程：按顺序取缓存中的 mp3 播放，响应 暂停/继续/停止/跳段。
UI 通过 Qt 信号接收进度（跨线程安全）。
"""
import hashlib
import os
import tempfile
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from PyQt5.QtCore import QObject, pyqtSignal

PREFETCH = 5


class Player(QObject):
    chunk_started = pyqtSignal(int, int)      # 当前段序号, 总段数
    round_changed = pyqtSignal(int, int)      # 当前遍数, 总遍数
    state_changed = pyqtSignal(str)           # playing / paused / stopped / finished
    status_text = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, tts):
        super().__init__()
        self.tts = tts
        self._cache = {}            # idx -> mp3 path
        self._chunks = []           # [(start, end, text)]
        self._voice = {}
        self._stop = threading.Event()
        self._paused = False
        self._skip_to = None        # 请求跳转的段号
        self._round = 1
        self._rounds = 1
        self._cur = 0
        self._threads = []
        self._tmpdir = tempfile.mkdtemp(prefix="reader_tts_")
        self._mixer_ok = False
        self._lock = threading.RLock()   # 串行化所有 SDL_mixer 调用，避免多线程并发崩溃
        self._active = False             # 是否处于一次朗读会话中
        self._bgm = {"path": "", "vol": 0.3, "on": False}
        self._bgm_loaded = None
        self._speech_ch = None           # 人声走通道；伴音走 music 流，二者互不干扰
        try:
            pygame.mixer.init()
            self._mixer_ok = True
            self._speech_ch = pygame.mixer.Channel(0)
        except pygame.error:
            pass

    # ---------------- 伴音 ----------------
    def set_bgm_volume(self, vol: float):
        """仅调音量（拖动滑杆用，极轻量，不处理开关）。"""
        self._bgm["vol"] = vol
        if self._mixer_ok:
            with self._lock:
                try:
                    pygame.mixer.music.set_volume(vol)
                except pygame.error:
                    pass

    def set_bgm(self, path: str, vol: float, on: bool):
        """设置伴音。vol 0.0~1.0。播放中会实时生效。"""
        self._bgm = {"path": path, "vol": vol, "on": on}
        if not self._mixer_ok:
            return
        if not on:
            self._stop_bgm()
        elif self._active:
            self._start_bgm()

    def _start_bgm(self):
        """伴音走 mixer.music 流：内存占用恒定，加载瞬时完成。"""
        b = self._bgm
        path = b["path"]
        if not (self._mixer_ok and b["on"] and path and os.path.exists(path)):
            return
        try:
            with self._lock:
                if self._bgm_loaded != path:
                    pygame.mixer.music.load(path)
                    self._bgm_loaded = path
                pygame.mixer.music.set_volume(b["vol"])
                if not pygame.mixer.music.get_busy():
                    pygame.mixer.music.play(loops=-1)
        except pygame.error as e:
            self.status_text.emit(f"伴音加载失败: {e}")

    def _stop_bgm(self):
        if not self._mixer_ok:
            return
        with self._lock:
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass

    # ---------------- 公共控制 ----------------
    def play(self, chunks, voice: dict, start_idx: int = 0, rounds: int = 1):
        self.stop(join=True)
        self._stop.clear()
        self._paused = False
        self._active = True
        self._cache.clear()
        self._chunks = chunks
        self._voice = voice
        self._rounds = max(1, rounds)
        self._round = 1
        self._cur = start_idx
        self._skip_to = None
        self._threads = [
            threading.Thread(target=self._synth_loop, daemon=True),
            threading.Thread(target=self._play_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        self._start_bgm()

    def pause(self):
        self._paused = True
        if self._mixer_ok:
            with self._lock:
                try:
                    if self._speech_ch:
                        self._speech_ch.pause()
                    pygame.mixer.music.pause()
                except pygame.error:
                    pass
        self.state_changed.emit("paused")

    def resume(self):
        self._paused = False
        if self._mixer_ok:
            with self._lock:
                try:
                    if self._speech_ch:
                        self._speech_ch.unpause()
                    pygame.mixer.music.unpause()
                except pygame.error:
                    pass
        self.state_changed.emit("playing")

    def stop(self, join: bool = False):
        self._stop.set()
        self._active = False
        if self._mixer_ok:
            with self._lock:
                try:
                    if self._speech_ch:
                        self._speech_ch.stop()
                except pygame.error:
                    pass
        self._stop_bgm()
        if join:
            for t in self._threads:
                t.join(timeout=2)
            self._threads = []

    def skip(self, delta: int):
        """跳到下一段/上一段。"""
        if not self._chunks:
            return
        target = max(0, min(len(self._chunks) - 1, self._cur + delta))
        self._skip_to = target
        if self._mixer_ok and self._speech_ch:
            with self._lock:
                try:
                    self._speech_ch.stop()
                except pygame.error:
                    pass

    @property
    def playing(self):
        return not self._stop.is_set()

    # ---------------- 内部线程 ----------------
    def _cache_path(self, idx: int) -> str:
        text = self._chunks[idx][2]
        h = hashlib.md5((text + str(sorted(self._voice.items()))).encode("utf-8")).hexdigest()
        return os.path.join(self._tmpdir, f"{h}.mp3")

    def _synth_loop(self):
        while not self._stop.is_set():
            target = min(len(self._chunks), self._cur + PREFETCH)
            did_work = False
            for idx in range(self._cur, target):
                if self._stop.is_set():
                    return
                if idx in self._cache and os.path.exists(self._cache[idx]):
                    continue
                path = self._cache_path(idx)
                if os.path.exists(path):
                    self._cache[idx] = path
                    continue
                try:
                    self.status_text.emit(f"正在合成第 {idx + 1}/{len(self._chunks)} 段…")
                    data = self.tts.synth(self._chunks[idx][2], **self._voice)
                    with open(path, "wb") as f:
                        f.write(data)
                    self._cache[idx] = path
                    did_work = True
                except Exception as e:
                    if not self._stop.is_set():
                        self.error.emit(str(e))
                        self._stop.set()
                        self._active = False
                        self._stop_bgm()
                        if self._mixer_ok and self._speech_ch:
                            with self._lock:
                                try:
                                    self._speech_ch.stop()
                                except pygame.error:
                                    pass
                    return
            if not did_work:
                time.sleep(0.15)

    def _play_loop(self):
        if not self._mixer_ok:
            self.error.emit("音频设备初始化失败，无法播放")
            return
        self.state_changed.emit("playing")
        while not self._stop.is_set() and self._round <= self._rounds:
            # 暂停等待：用户点了暂停 → 直到 resume/stop 才往下
            while self._paused and not self._stop.is_set():
                time.sleep(0.05)
            if self._stop.is_set():
                break
            if self._skip_to is not None:
                self._cur = self._skip_to
                self._skip_to = None
            if self._cur >= len(self._chunks):
                self._round += 1
                self._cur = 0
                if self._round > self._rounds:
                    break
                self.round_changed.emit(self._round, self._rounds)
                continue
            idx = self._cur
            self.round_changed.emit(self._round, self._rounds)
            # 等待该段合成完成
            while idx not in self._cache and not self._stop.is_set() and self._skip_to is None:
                time.sleep(0.1)
            if self._stop.is_set():
                break
            if self._skip_to is not None:
                continue
            self.chunk_started.emit(idx, len(self._chunks))
            self.status_text.emit(f"朗读中 第 {idx + 1}/{len(self._chunks)} 段")
            try:
                snd = pygame.mixer.Sound(self._cache[idx])
            except pygame.error as e:
                self.error.emit(f"播放失败: {e}")
                break
            vol = self._voice.get("vol", 5) / 15.0
            with self._lock:
                self._speech_ch.set_volume(max(0.05, vol))
                self._speech_ch.play(snd)
            # 播放中等待：同时监控 stop / skip / paused
            while self._speech_ch.get_busy() and not self._stop.is_set():
                if self._skip_to is not None:
                    break
                if self._paused:
                    self._speech_ch.pause()
                    pygame.mixer.music.pause()
                    while self._paused and not self._stop.is_set():
                        time.sleep(0.05)
                    if self._stop.is_set():
                        break
                    if self._skip_to is not None:
                        self._speech_ch.stop()
                        break
                    self._speech_ch.unpause()
                    pygame.mixer.music.unpause()
                time.sleep(0.05)
            if self._skip_to is not None:
                continue
            if self._stop.is_set():
                break
            self._cur += 1
        self._active = False
        if not self._stop.is_set():
            self._stop_bgm()
            self.state_changed.emit("finished")
            self.status_text.emit("朗读完成")
        else:
            self.state_changed.emit("stopped")

    # ---------------- 导出 MP3 ----------------
    def export_mp3(self, chunks, voice: dict, out_path: str, progress=None):
        """把全文合成并拼接为一个 mp3 文件（同步执行，请在子线程调用）。"""
        old_chunks, old_voice = self._chunks, self._voice
        try:
            self._chunks, self._voice = chunks, voice
            with open(out_path, "wb") as out:
                for i, (_, _, text) in enumerate(chunks):
                    path = self._cache.get(i)
                    if not path or not os.path.exists(path):
                        path = self._cache_path(i)
                        if not os.path.exists(path):
                            data = self.tts.synth(text, **voice)
                            with open(path, "wb") as f:
                                f.write(data)
                        self._cache[i] = path
                    with open(path, "rb") as f:
                        out.write(f.read())
                    if progress:
                        progress(i + 1, len(chunks))
        finally:
            self._chunks, self._voice = old_chunks, old_voice
