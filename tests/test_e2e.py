# -*- coding: utf-8 -*-
"""端到端测试: 起服务 → 提交任务 → 校验产物 / 进度 / 取消

前置: 存在测试音频(见 tests/README), 需要模型已就位。
运行: python tests/test_e2e.py [音频路径]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "testdata" / "speech.wav"
PORT = 8912
BASE = f"http://127.0.0.1:{PORT}"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def http(path, data=None, token=None, method=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"))
    if body:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Token", token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def wait_server(proc, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            http("/api/state")
        except urllib.error.HTTPError as e:
            if e.code == 401:      # 服务已就绪, 只是没带令牌
                return True
            time.sleep(0.5)
            continue
        except Exception:
            time.sleep(0.5)
            continue
        return True
    return False


def main():
    if not AUDIO.exists():
        print(f"缺少测试音频: {AUDIO}")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="zx-e2e-"))
    log = open(tmp / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--no-window",
         "--port", str(PORT), "--data-dir", str(tmp)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait_server(proc):
            print("服务未启动"); return 1
        # app.url 在服务起来后 0.6s 才写, 需要短暂等待
        url_file = tmp / "app.url"
        for _ in range(40):
            if url_file.exists():
                break
            time.sleep(0.25)
        token = json.loads(url_file.read_text(encoding="utf-8"))["token"]

        print("\n[正常流程]")
        added = http("/api/tasks", {"paths": [str(AUDIO)]}, token)["added"]
        check("任务已入队", len(added) == 1, str(added))
        tid = added[0]["id"]

        samples, seen_done = [], False
        for _ in range(240):
            st = http("/api/state", token=token)
            t = next(x for x in st["tasks"] if x["id"] == tid)
            samples.append(round(t["progress"] * 100))
            if t["status"] in ("done", "failed", "canceled"):
                seen_done = t["status"] == "done"
                break
            time.sleep(1)

        check("任务完成", seen_done, t.get("error", ""))
        mono = all(b >= a - 1 for a, b in zip(samples, samples[1:]))
        check("进度单调不倒退", mono, str(samples[:12]))
        check("进度覆盖多档", len(set(samples)) >= 3, str(sorted(set(samples))[:10]))
        check("进度收尾到 100", samples[-1] == 100, str(samples[-3:]))

        outs = t.get("outputs") or {}
        for key, label in (("record", "文字记录.docx"), ("srt", "字幕.srt"),
                           ("txt", "转写.txt"), ("audio", "音频.mp3")):
            p = outs.get(key)
            check(f"产物存在: {label}", bool(p) and Path(p).exists(), str(p))
        check("产出目录存在", bool(outs.get("folder")) and Path(outs["folder"]).is_dir())

        print("\n[取消流程]")
        # 长音频才能稳定落在"运行中"; 没给长文件就退化为快速取消
        long_audio = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        cancel_src = long_audio if (long_audio and long_audio.exists()) else AUDIO
        print(f"  文件: {cancel_src}")
        added2 = http("/api/tasks", {"paths": [str(cancel_src)]}, token)["added"]
        tid2 = added2[0]["id"]
        time.sleep(4.0 if cancel_src is not AUDIO else 1.0)
        http(f"/api/tasks/{tid2}/cancel", {}, token)
        canceled = False
        for _ in range(60):
            st = http("/api/state", token=token)
            t2 = next(x for x in st["tasks"] if x["id"] == tid2)
            if t2["status"] in ("canceled", "done", "failed"):
                canceled = t2["status"] == "canceled"
                print(f"  终态: {t2['status']} 阶段={t2['stage']} 错误={(t2.get('error') or '')[:50]}")
                break
            time.sleep(1)
        check("运行中任务可取消", canceled, t2.get("status", ""))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n通过 {len(PASS)} 项, 失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
