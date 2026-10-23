# -*- coding: utf-8 -*-
"""命名规范与通用工具"""
import json
import re
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".wmv",
              ".m4v", ".ts", ".mpg", ".mpeg", ".3gp", ".rmvb", ".rm",
              ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".wma", ".amr"}

# 文件名里的噪声词: 分辨率、编码、平台水印、录屏默认名等, 命名时剔除
_NOISE = re.compile(
    r"(?i)\b(1080p|720p|480p|2160p|4k|8k|hd|fhd|uhd|hdr|x264|x265|h264|h265|"
    r"hevc|avc|aac|mp3|mp4|web-?dl|bluray|bdrip|hdtv|dvdrip|"
    r"official|music\s*video|lyrics?|sub(?:title)?s?|"
    r"vid|dsc|img|mov|screen\s*recording|recording|screen|"
    r"录屏|屏幕录制|手机录制|录音|视频|音频|直播|回放|"
    r"untitled|video|audio|new|final|copy)\b")
_LABEL_MAX = 18      # 标签正文最长字数, 超出截断


def clean_label(name: str) -> str:
    """把原始文件名清洗成简短内容标签: 去日期时间、去噪声词、压空白"""
    s = name
    # 日期
    s = re.sub(r"20\d{2}\s*[-_.年/]\s*\d{1,2}\s*[-_.月/]\s*\d{1,2}\s*[日号]?", "", s)
    s = re.sub(r"(?<!\d)20\d{6}(?!\d)", "", s)
    s = re.sub(r"(?<!\d)\d{6,8}(?!\d)", "", s)
    # 时间片段 15-30 / 15:30:12 / 15.30
    s = re.sub(r"(?<!\d)\d{1,2}\s*[-.:]\s*\d{2}(?:\s*[-.:]\s*\d{2})?(?!\d)", " ", s)
    # 分隔符转空格, 否则 \b 边界匹配不到英文噪声词
    s = re.sub(r"[_\-—+~·|.]+", " ", s)
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[【】\[\]()（）{}<>《》]", " ", s)
    s = re.sub(r"(?i)\b(?:at|on|of|the)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ._-")
    if len(s) > _LABEL_MAX:
        s = s[:_LABEL_MAX].rstrip(" ._-")
    # 只剩无意义残留(VID / at / 单字母)时给个占位
    if not s or (s.isascii() and len(s) <= 3):
        return "未命名"
    return s


def canonical_stem(video: Path) -> tuple[str, datetime]:
    """规范名 = 修改时间 + 简短内容标签, 如 2026-08-22_15-30_理财咨询"""
    mtime = datetime.fromtimestamp(video.stat().st_mtime)
    return f"{mtime:%Y-%m-%d}_{mtime:%H-%M}_{clean_label(video.stem)}", mtime


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
