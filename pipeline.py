#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转写助手 · 命令行模式 (复用软件内核, 适合无界面/批处理)

用法:
  python pipeline.py all [--model large-v3] [--force]   # 处理 01_视频/ 下所有视频
  python pipeline.py md2docx 文件.md                     # 总结 Markdown -> Word
"""
import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="转写助手命令行")
    ap.add_argument("task", choices=["all", "md2docx"])
    ap.add_argument("md", nargs="?", help="md2docx 用的 Markdown 文件")
    ap.add_argument("--model", default=None, help="large-v3/distil-large-v3/medium/small/tiny")
    ap.add_argument("--force", action="store_true", help="已存在也重新处理")
    args = ap.parse_args()

    if args.task == "md2docx":
        md = Path(args.md)
        if not md.exists():
            print(f"文件不存在: {md}")
            return 1
        from backend.docgen import md_to_docx
        out = md_to_docx(md.read_text(encoding="utf-8"), md.with_suffix(".docx"))
        print(f"已生成 -> {out}")
        return 0

    from backend.tasks import Worker
    worker = Worker(BASE)
    s = worker.settings
    if args.model:
        s["transcribe"]["tier"] = args.model
        worker.save_settings(s)
    videos = sorted(p for p in (BASE / "01_视频").iterdir()
                    if p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".flv",
                                            ".webm", ".wmv", ".m4v", ".mp3", ".m4a",
                                            ".aac", ".wav", ".flac", ".ogg"})
    if not videos:
        print("01_视频/ 中没有视频")
        return 1
    added = worker.add_paths([str(v) for v in videos])
    new_ids = {t["id"] for t in added}
    print(f"已加入 {len(added)} 个任务: {', '.join(v.name for v in videos)}")
    worker.start()
    while True:
        tasks = worker.list_tasks()
        active = [t for t in tasks if t["id"] in new_ids
                  and t["status"] in ("queued", "running")]
        if not active:
            break
        cur = [t for t in tasks if t["status"] == "running"]
        if cur:
            t = cur[0]
            print(f"\r{t['video']} | {t['stage']} {int((t['progress'] or 0)*100)}%", end="", flush=True)
        else:
            print("\r等待中...", end="", flush=True)
        time.sleep(1)
    print()
    ok = sum(1 for t in worker.list_tasks()
             if t["id"] in new_ids and t["status"] == "done")
    print(f"完成 {ok}/{len(added)} 个任务")
    return 0 if ok == len(added) else 1


if __name__ == "__main__":
    sys.exit(main())
