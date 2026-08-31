# -*- coding: utf-8 -*-
"""转写助手 入口

用法:
  python app.py                  # 打开软件窗口 (优先 pywebview 原生窗口, 失败则浏览器)
  python app.py --no-window      # 只启动本地服务 (测试/无头环境用)
  python app.py --port 8765      # 指定端口 (默认自动选)
"""
import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# 打包后数据目录跟随 exe 所在位置, 保证用户可写、可迁移
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent


def find_free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main():
    ap = argparse.ArgumentParser(description="转写助手")
    ap.add_argument("--no-window", action="store_true", help="只启动本地服务, 不开窗口")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    from backend.server import create_app
    from backend.tasks import Worker

    worker = Worker(BASE)
    worker.start()
    app = create_app(BASE, worker)
    port = args.port or find_free_port()
    url = f"http://127.0.0.1:{port}"
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               use_reloader=False),
        daemon=True)
    server.start()
    print(f"转写助手服务已启动: {url}")

    if args.no_window:
        print("无窗口模式运行中 (Ctrl+C 退出)")
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
        def choose_files(self):
            import webview as wv
            win = wv.windows[0] if wv.windows else None
            if not win:
                return []
            files = win.create_file_dialog(
                wv.FILE_DIALOG, allow_multiple=True,
                file_types=("视频文件 (*.mp4;*.mkv;*.mov;*.avi;*.flv;*.webm;"
                            "*.mp3;*.m4a;*.wav;*.aac)", "所有文件 (*.*)"))
            return list(files) if files else []

        def open_folder(self, path):
            import os
            p = Path(path).parent
            if p.exists():
                if os.name == "nt":
                    os.startfile(str(p))  # noqa: S606
                else:
                    webbrowser.open(str(p))

        def exit_app(self):
            import webview as wv
            for win in wv.windows:
                win.destroy()

    api = Api()
    try:
        webview.create_window(
            "转写助手", url, js_api=api, width=1180, height=820,
            min_size=(960, 640), text_select=True)
        webview.start()
    except Exception as e:
        print(f"窗口启动失败({e}), 改为浏览器打开: {url}")
        webbrowser.open(url)
        threading.Event().wait()


if __name__ == "__main__":
    main()
