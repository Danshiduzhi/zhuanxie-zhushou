# -*- coding: utf-8 -*-
"""日志: 写文件 + 保留最近一份轮转, 供界面"查看日志"和用户排错"""
import logging
import logging.handlers
from pathlib import Path

_LOGGER = None


def setup(log_file: Path, level=logging.INFO) -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("zhuanxie")
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    _LOGGER = logger
    return logger


def get() -> logging.Logger:
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = logging.getLogger("zhuanxie")
        _LOGGER.addHandler(logging.NullHandler())
    return _LOGGER


def tail(log_file: Path, lines: int = 200) -> str:
    """读日志尾部, 界面用"""
    if not log_file.exists():
        return ""
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except Exception as e:
        return f"读取日志失败: {e}"
