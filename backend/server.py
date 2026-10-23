# -*- coding: utf-8 -*-
"""Flask API: 任务/设置/上传/试听/打开文件夹

本机服务只为当前用户服务, 但仍加一次性令牌:
其他进程或恶意网页即使用端口扫到了, 没有令牌也调不动接口。
"""
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import applog, config, engine, paths
from .tasks import Worker

# 打包后前端页面从解包目录读取, 源码模式从项目目录读取
if getattr(sys, "frozen", False):
    FRONTEND = Path(getattr(sys, "_MEIPASS", "")) / "frontend"
else:
    FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

APP_VERSION = "2.0"


def create_app(dirs: dict, worker: Worker, token: str) -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="/static")
    log = applog.get()

    def _allowed_roots():
        """允许打开的范围: 当前工作目录 + 程序目录(工作目录可能被用户改过)"""
        return {Path(dirs["root"]).resolve(), Path(paths.app_dir()).resolve()}

    def public(t):
        outs = t.get("outputs") or {}
        return {
            "id": t["id"], "video": t["video"], "stem": t["stem"],
            "created": t["created"], "status": t["status"], "stage": t["stage"],
            "progress": t["progress"], "error": t.get("error"),
            "outputs": outs, "doubtful": t.get("doubtful") or [],
            "meta": t.get("meta") or {},
        }

    # ---------- 鉴权 ----------
    OPEN_PATHS = {"/", "/index.html", "/style.css", "/app.js", "/favicon.ico",
                  "/donate.png"}

    @app.before_request
    def _check_token():
        if request.path in OPEN_PATHS or request.path.startswith("/static/"):
            return None
        if request.path.startswith("/api/"):
            sent = request.headers.get("X-Token") or request.args.get("token", "")
            if sent != token:
                return jsonify({"error": "unauthorized"}), 401
        return None

    # ---------- 页面 ----------
    @app.route("/")
    def index():
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        # 令牌注入页面, 前端所有请求带上
        html = html.replace("</head>",
                            f'<script>window.__ZX_TOKEN="{token}";</script></head>')
        return html

    @app.get("/style.css")
    def _css():
        return send_from_directory(FRONTEND, "style.css")

    @app.get("/app.js")
    def _js():
        return send_from_directory(FRONTEND, "app.js")

    @app.get("/donate.png")
    def _donate():
        f = FRONTEND / "donate.png"
        if f.exists():
            return send_from_directory(FRONTEND, "donate.png")
        return "", 204

    # ---------- 状态 ----------
    @app.get("/api/state")
    def state():
        tasks = sorted(worker.list_tasks(),
                       key=lambda t: float(t.get("created") or 0))
        return jsonify({
            "tasks": [public(t) for t in tasks],
            "settings": worker.settings,
            "hardware": engine.detect_hardware(),
            "dirs": {"root": str(dirs["root"]), "docs": str(dirs["docs"])},
            "version": APP_VERSION,
        })

    # ---------- 设置 ----------
    @app.post("/api/settings")
    def save_settings():
        data = request.get_json(force=True) or {}
        old_cfg = dict(worker.settings or {})
        merged = config._merge_defaults({**old_cfg, **data})
        cfg_path = Path(dirs["config"])
        config.save(cfg_path, merged)
        worker.save_settings(merged)

        # 工作目录变更: 重新建目录并切换
        new_root = (merged.get("work_root") or "").strip()
        target = Path(new_root).expanduser().resolve() if new_root else Path(dirs["root"])
        if target != Path(dirs["root"]).resolve():
            new_dirs = paths.ensure(target)
            dirs.update(new_dirs)
            worker.relocate(new_dirs)
            log.info("工作目录切换到 %s", target)
        return jsonify({"ok": True, "root": str(dirs["root"])})

    # ---------- 任务 ----------
    @app.post("/api/tasks")
    def add_tasks():
        data = request.get_json(force=True) or {}
        added = worker.add_paths(data.get("paths", []))
        log.info("添加任务 %d 个", len(added))
        return jsonify({"added": [public(t) for t in added]})

    @app.post("/api/upload")
    def upload():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "未收到文件"}), 400
        name = Path(f.filename).name
        target = Path(dirs["video"]) / name
        if target.exists():
            target = Path(dirs["video"]) / f"{target.stem}_{int(time.time())}{target.suffix}"
        f.save(str(target))
        added = worker.add_paths([str(target)], is_copy=True)
        log.info("上传文件: %s", name)
        return jsonify({"added": [public(t) for t in added]})

    @app.post("/api/tasks/<task_id>/retry")
    def retry(task_id):
        worker.retry(task_id)
        return jsonify({"ok": True})

    @app.post("/api/tasks/<task_id>/cancel")
    def cancel(task_id):
        worker.cancel(task_id)
        return jsonify({"ok": True})

    @app.post("/api/tasks/<task_id>/delete")
    def delete(task_id):
        worker.delete(task_id)
        return jsonify({"ok": True})

    @app.post("/api/tasks/clear")
    def clear():
        """批量删除终态任务记录"""
        data = request.get_json(force=True) or {}
        states = set(data.get("statuses") or ["failed", "canceled", "interrupted"])
        for t in worker.list_tasks():
            if t["status"] in states:
                worker.delete(t["id"])
        return jsonify({"ok": True})

    @app.get("/api/audio/<task_id>")
    def audio(task_id):
        t = worker.get_task(task_id)
        if not t or not (t.get("outputs") or {}).get("audio"):
            return jsonify({"error": "无音频"}), 404
        path = t["outputs"]["audio"]
        if not Path(path).exists():
            return jsonify({"error": "音频已删除"}), 404
        return send_from_directory(os.path.dirname(path),
                                   os.path.basename(path), conditional=True)

    # ---------- 打开位置 ----------
    def _in_roots(p: Path) -> bool:
        rp = p.resolve()
        return any(rp == r or r in rp.parents for r in _allowed_roots())

    @app.post("/api/open")
    def open_path():
        """在文件管理器中打开文件或所在文件夹"""
        data = request.get_json(force=True) or {}
        raw = data.get("path", "")
        if not raw:
            return jsonify({"error": "缺少路径"}), 400
        target = Path(raw)
        if not _in_roots(target):
            return jsonify({"error": "路径不在允许范围"}), 403
        folder = target if target.is_dir() else target.parent
        if not folder.exists():
            return jsonify({"error": "路径不存在"}), 404
        try:
            system = platform.system()
            if system == "Windows":
                if target.is_file():
                    subprocess.Popen(["explorer", "/select,", str(target)])
                else:
                    os.startfile(str(folder))  # noqa: S606
            elif system == "Darwin":
                if target.is_file():
                    subprocess.Popen(["open", "-R", str(target)])
                else:
                    subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            log.warning("打开路径失败: %s", e)
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True})

    @app.post("/api/open-file")
    def open_file():
        """用系统默认程序打开单个文件(Word/字幕)"""
        data = request.get_json(force=True) or {}
        target = Path(data.get("path", ""))
        if not target.exists() or not _in_roots(target):
            return jsonify({"error": "文件不存在"}), 404
        try:
            if platform.system() == "Windows":
                os.startfile(str(target))  # noqa: S606
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True})

    # ---------- 日志 ----------
    @app.get("/api/log")
    def log_tail():
        return jsonify({"log": applog.tail(Path(dirs["log_file"]), 300),
                        "file": str(dirs["log_file"])})

    return app
