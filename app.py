# -*- coding: utf-8 -*-
"""转写助手 入口

用法:
  python app.py                  # 打开软件窗口 (优先 pywebview 原生窗口, 失败则浏览器)
  python app.py --no-window      # 只启动本地服务 (测试/无头环境用)
  python app.py --port 8765      # 指定端口 (默认自动选)
  python app.py --data-dir D:\\x  # 指定数据目录 (默认用户目录/程序目录)
  python app.py --portable       # 绿色模式: 数据放程序目录 (等价于放 portable.flag)
"""
import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from backend import applog, config, paths

LOCK_PORT = 8799          # 单实例锁: 谁先占住这个端口谁是唯一实例
URL_FILE = "app.url"      # 记录当前实例的地址与令牌, 供第二次启动时直接打开


def find_free_port(start=8765, span=50):
    for port in range(start, start + span):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def acquire_single_instance() -> socket.socket | None:
    """抢占单实例锁; 抢不到返回 None (说明已有实例在跑)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def open_existing(roots) -> bool:
    """已有实例: 读出地址直接打开界面"""
    for cand in roots:
        f = Path(cand) / URL_FILE
        if not f.exists():
            continue
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            url = info.get("url") or ""
            if url:
                webbrowser.open(url)
                print(f"软件已在运行: {url}")
                return True
        except Exception:
            continue
    return False


def main():
    ap = argparse.ArgumentParser(description="转写助手")
    ap.add_argument("--no-window", action="store_true", help="只启动本地服务, 不开窗口")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--portable", action="store_true", help="绿色模式: 数据放程序目录")
    ap.add_argument("--view", default="", choices=["", "tasks", "history", "settings"],
                    help="启动时直接打开指定页面")
    args = ap.parse_args()

    if args.portable:
        os.environ["ZX_PORTABLE"] = "1"

    root = paths.data_dir(args.data_dir or None)
    dirs = paths.ensure(root)
    applog.setup(Path(dirs["log_file"]))
    log = applog.get()

    # 单实例: 已经有一份在跑就不重复启动, 直接把界面带出来
    lock = acquire_single_instance()
    if lock is None and not args.no_window:
        if open_existing((root, paths.app_dir())):
            return
        # 端口可能被别的程序占用, 不能因此拒绝启动
        log.warning("单实例端口 %d 被占用且未找到已有实例, 继续启动", LOCK_PORT)

    from backend.server import create_app
    from backend.tasks import Worker

    cfg = config.load(Path(dirs["config"]), paths.app_dir() / "config.json")
    work_root = (cfg.get("work_root") or "").strip()
    if work_root:
        try:
            dirs = paths.ensure(Path(work_root).expanduser().resolve())
            log.info("使用自定义工作目录: %s", work_root)
        except Exception as e:
            log.warning("工作目录不可用(%s), 回退默认目录", e)

    def persist_settings(new_cfg: dict):
        config.save(Path(dirs["config"]), new_cfg)

    worker = Worker(dirs, cfg, on_settings_saved=persist_settings)
    worker.start()

    token = secrets.token_hex(16)
    app = create_app(dirs, worker, token)

    port = args.port or find_free_port()
    if not port:
        port = 8765
    url = f"http://127.0.0.1:{port}"
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               use_reloader=False, threaded=True),
        daemon=True).start()
    time.sleep(0.6)
    log.info("服务已启动: %s (数据目录 %s)", url, dirs["root"])

    try:
        (Path(dirs["root"]) / URL_FILE).write_text(
            json.dumps({"url": url, "token": token, "pid": os.getpid(),
                        "version": "running"},
                       ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    if args.no_window:
        print(f"转写助手服务已启动: {url}")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        print("未安装 pywebview, 已在浏览器中打开。安装后可获得原生窗口: "
              "pip install pywebview")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    class Api:
        """暴露给前端的原生能力 (文件选择对话框等)"""

        def choose_files(self):
            import webview as wv
            win = wv.windows[0] if wv.windows else None
            if not win:
                return []
            files = win.create_file_dialog(
                wv.OPEN_DIALOG, allow_multiple=True,
                file_types=("媒体文件 (*.mp4;*.mkv;*.mov;*.avi;*.flv;*.webm;"
                            "*.mp3;*.m4a;*.wav;*.aac;*.flac;*.ogg)",
                            "所有文件 (*.*)"))
            return list(files) if files else []

        def get_dirs(self):
            return {"root": str(dirs["root"]), "docs": str(dirs["docs"])}

        def show_in_folder(self, path):
            """在资源管理器里定位文件"""
            from pathlib import Path as P
            p = P(path)
            target = p if p.exists() else P(dirs["docs"])
            folder = target if target.is_dir() else target.parent
            if os.name == "nt":
                if target.is_file():
                    import subprocess
                    subprocess.Popen(["explorer", "/select,", str(target)])
                else:
                    os.startfile(str(folder))  # noqa: S606
            else:
                webbrowser.open(str(folder))

        def open_file(self, path):
            """用系统默认程序打开文件(三平台都支持, 桌面端功能对齐)"""
            target = Path(path)
            if not target.exists():
                return
            try:
                if os.name == "nt":
                    os.startfile(str(target))  # noqa: S606
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", str(target)])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", str(target)])
            except Exception:
                pass

        def exit_app(self):
            import webview as wv
            for win in wv.windows:
                win.destroy()

    try:
        webview.create_window(
            "转写助手", url + (f"#{args.view}" if args.view else ""),
            js_api=Api(), width=1160, height=800,
            min_size=(940, 620), text_select=True,
            background_color="#f5f5f7")
        webview.start()
    except Exception as e:
        log.exception("窗口启动失败: %s", e)
        print(f"窗口启动失败({e}), 改为浏览器打开: {url}")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
