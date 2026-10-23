# -*- coding: utf-8 -*-
"""路径解析: 程序目录(只读) 与 数据目录(可写) 分离

- 程序目录: exe / 源码所在处, 存放 frontend、models、ffmpeg 等只读资源
- 数据目录: 配置、任务记录、日志、转写产物; 打包运行时装在用户目录,
  这样程序可以装到 Program Files(无写权限)也不会坏, 卸载也不会删掉用户数据

绿色版(便携版): 程序目录下放一个 portable.flag 文件即可让数据跟随程序目录
"""
import os
import sys
from pathlib import Path

APP_NAME = "转写助手"
APP_ID = "ZhuanXieZhuShou"


def app_dir() -> Path:
    """程序目录: 打包后是 exe 所在目录, 源码运行是项目根目录"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _user_data_root() -> Path:
    """用户数据根目录 (Windows: %LOCALAPPDATA%\\转写助手)"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    # macOS / Linux
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_NAME


def _has_user_data(p: Path) -> bool:
    """目录里是否已有用户数据(历史版本把数据写在程序目录)"""
    for d in ("01_视频", "02_音频", "03_转写", "04_文档"):
        sub = p / d
        if sub.is_dir() and any(sub.iterdir()):
            return True
    return False


def data_dir(override: str | None = None) -> Path:
    """数据目录优先级: 命令行 > 环境变量 > 便携标记 > 用户目录(打包) / 程序目录(源码)"""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ZX_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()

    app = app_dir()
    portable = (app / "portable.flag").exists() or bool(os.environ.get("ZX_PORTABLE"))
    if portable:
        return app
    if not getattr(sys, "frozen", False):
        return app  # 源码运行: 保持原有开发习惯
    # 兼容历史版本: 若程序目录里已经存了用户数据, 继续用原地, 避免用户找不到
    if _has_user_data(app):
        return app
    return _user_data_root()


def ensure(root: Path) -> dict:
    """建好目录并返回各子路径"""
    dirs = {
        "root": root,
        "video": root / "01_视频",
        "audio": root / "02_音频",
        "text": root / "03_转写",
        "docs": root / "04_文档",
        "data": root / "data",
        "logs": root / "logs",
    }
    for d in ("video", "audio", "text", "docs", "data", "logs"):
        dirs[d].mkdir(parents=True, exist_ok=True)
    dirs["config"] = root / "config.json"
    dirs["tasks"] = dirs["data"] / "tasks.json"
    dirs["log_file"] = dirs["logs"] / "app.log"
    return dirs


def models_dir() -> Path:
    """模型目录: 优先程序目录(随包分发), 其次数据目录(下载缓存)"""
    app = app_dir()
    for cand in (app / "models", data_dir() / "models"):
        if cand.is_dir():
            return cand
    return app / "models"
