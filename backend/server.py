# -*- coding: utf-8 -*-
"""Flask API 服务器: 任务/设置/上传/试听/打开文件夹"""
import os
import platform
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import engine
from .tasks import Worker

# 打包后前端页面从解包目录读取, 源码模式从项目目录读取
if getattr(sys, "frozen", False):
    FRONTEND = Path(getattr(sys, "_MEIPASS", "")) / "frontend"
else:
    FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def create_app(base: Path, worker: Worker | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")
    worker = worker or Worker(base)

    def public(t):
        return {k: t[k] for k in
                ("id", "video", "stem", "created", "status", "stage",
                 "progress", "error", "outputs", "doubtful", "meta")}

    @app.route("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/api/state")
    def state():
        return jsonify({"tasks": [public(t) for t in worker.list_tasks()],
                        "settings": worker.settings,
                        "hardware": engine.detect_hardware()})

    @app.post("/api/settings")
    def save_settings():
        data = request.get_json(force=True)
        worker.save_settings(data)
        return jsonify({"ok": True})

    @app.post("/api/tasks")
    def add_tasks():
        data = request.get_json(force=True) or {}
        added = worker.add_paths(data.get("paths", []))
        return jsonify({"added": [public(t) for t in added]})

    @app.post("/api/upload")
    def upload():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "未收到文件"}), 400
        target = worker.dir_video / f.filename
        if target.exists():
            target = worker.dir_video / f"{target.stem}_{int(__import__('time').time())}{target.suffix}"
        f.save(str(target))
        added = worker.add_paths([str(target)])
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

    @app.get("/api/audio/<task_id>")
    def audio(task_id):
        t = worker.get_task(task_id)
        if not t or "audio" not in t.get("outputs", {}):
            return jsonify({"error": "无音频"}), 404
        path = t["outputs"]["audio"]
        return send_from_directory(os.path.dirname(path),
                                   os.path.basename(path), conditional=True)

    @app.post("/api/open-folder")
    def open_folder():
        data = request.get_json(force=True) or {}
        path = data.get("path", "")
        if path and Path(path).exists():
            if platform.system() == "Windows":
                os.startfile(str(Path(path).parent))  # noqa: S606
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(Path(path).parent)])
            else:
                subprocess.Popen(["xdg-open", str(Path(path).parent)])
        return jsonify({"ok": True})

    @app.get("/api/log")
    def log():
        return jsonify({"log": ""})

    return app
