# -*- coding: utf-8 -*-
"""命名规范与通用工具"""
import json
import re
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".wmv",
              ".m4v", ".ts", ".mpg", ".mpeg", ".3gp", ".rmvb", ".rm",
              ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".wma", ".amr"}


def canonical_stem(video: Path) -> tuple[str, datetime]:
    """规范名 = 视频修改时间 + 去日期后的内容词, 如 2026-08-22_15-30_产品评审会"""
    mtime = datetime.fromtimestamp(video.stat().st_mtime)
    stem = video.stem
    cleaned = re.sub(r"20\d{2}\s*[-_.年/]\s*\d{1,2}\s*[-_.月/]\s*\d{1,2}", "", stem)
    cleaned = re.sub(r"(?<!\d)20\d{6}(?!\d)", "", cleaned)  # 20260822
    cleaned = re.sub(r"[【】\[\]()（）{}]", " ", cleaned)
    cleaned = re.sub(r"[\s_\-—]+", "_", cleaned).strip("_ .")
    content = cleaned or "未命名"
    return f"{mtime:%Y-%m-%d}_{mtime:%H-%M}_{content}", mtime


def unique_path(p: Path) -> Path:
    """若文件已存在则加 _2/_3 后缀, 避免覆盖"""
    if not p.exists():
        return p
    for i in range(2, 100):
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError(f"无法为 {p} 找到不冲突的文件名")


def ts(sec: float, total: float = 0) -> str:
    m, s = divmod(max(0, int(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if total >= 3600 else f"{m:02d}:{s:02d}"


def ts_to_sec(t: str) -> int:
    parts = [int(x) for x in re.split(r"[:：]", t)]
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}
