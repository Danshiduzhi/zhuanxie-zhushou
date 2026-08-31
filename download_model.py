#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 ModelScope 多线程分块下载 faster-whisper 模型到本地 models/ 目录
用法: python download_model.py [模型名]
模型名: faster-whisper-large-v3(默认) / distil-large-v3 / medium / small / tiny
"""
import concurrent.futures
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODELS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-large-v3": "Systran/faster-whisper-distil-large-v3",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "tiny": "Systran/faster-whisper-tiny",
}
CHUNK = 8 * 1024 * 1024  # 8MB/块
WORKERS = 6


def http_size(url: str) -> int:
    """用 1 字节范围请求探测文件总大小 (HEAD 不可靠)"""
    out = subprocess.run(["curl", "-sL", "-r", "0-0", "-o", "/dev/null",
                          "-D", "-", url], capture_output=True, text=True).stdout
    m = re.search(r"(?i)content-range:\s*bytes\s+\d+-\d+/(\d+)", out)
    return int(m.group(1)) if m else 0


def fetch_range(url: str, start: int, end: int, out: Path):
    subprocess.run(["curl", "-s", "-L", "-r", f"{start}-{end}",
                    "-o", str(out), url], check=True)


def download(model: str):
    repo = MODELS[model]
    target = BASE / "models" / model
    target.mkdir(parents=True, exist_ok=True)
    base_url = f"https://modelscope.cn/models/{repo}/resolve/master"
    # 小文件直接下
    for f in ("config.json", "tokenizer.json", "vocabulary.json",
              "preprocessor_config.json"):
        p = target / f
        if not p.exists():
            subprocess.run(["curl", "-s", "-L", "-o", str(p),
                            f"{base_url}/{f}"], check=True)
            print(f"  {f} OK")
    # model.bin 分块并发
    bin_url = f"{base_url}/model.bin"
    size = http_size(bin_url)
    if size <= 0:
        raise RuntimeError(f"无法获取 model.bin 大小: {bin_url}")
    out = target / "model.bin"
    if out.exists() and out.stat().st_size == size:
        print(f"model.bin 已存在且完整 ({size} 字节)")
        return
    print(f"model.bin 总大小 {size/1024/1024:.0f}MB, {WORKERS} 线程分块下载...")
    ranges = [(s, min(s + CHUNK - 1, size - 1)) for s in range(0, size, CHUNK)]
    tmp = BASE / "models" / f".{model}.tmp"
    tmp.mkdir(exist_ok=True)
    files = [tmp / f"{i:05d}" for i in range(len(ranges))]
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(fetch_range, bin_url, st, en, f)
                for (st, en), f in zip(ranges, files)]
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            fut.result()
            done += 1
            print(f"\r  {done}/{len(ranges)} 块完成", end="", flush=True)
    print()
    with open(out, "wb") as o:
        for f in files:
            o.write(f.read_bytes())
            f.unlink()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"完成: {out} ({out.stat().st_size} 字节)")


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "faster-whisper-large-v3"
    if model not in MODELS:
        print(f"支持的模型: {', '.join(MODELS)}")
        sys.exit(1)
    download(model)
