"""配置读写：config.json 保存在程序目录。"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "api_key": "",
    "secret_key": "",
    "per": 0,
    "spd": 5,
    "pit": 5,
    "vol": 10,
    "rounds": 1,
    "bgm_on": False,
    "bgm_path": "",
    "bgm_list": [],       # 最多 5 首备用音乐路径
    "bgm_index": -1,      # 当前选中序号（-1 = 未选）
    "bgm_vol": 30,
    "bg_path": "",
    "bg_opacity": 30,
    "font_size": 11,
    "text_color": "#000000",
    "hl_color": "#fff3a0",
    "doc_bg": "#ffffff",
    "para_spacing": 0,
}


def get_spacing(cfg: dict) -> int:
    """段落间距（像素，-20~30）。兼容旧的百分比配置。"""
    v = int(cfg.get("para_spacing", 0))
    return v if -20 <= v <= 30 else 0


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
