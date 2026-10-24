# -*- coding: utf-8 -*-
"""任务队列与持久化: 单线程顺序处理, 状态落盘, 支持断点续跑与中途取消"""
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import applog, docgen, engine, proofread
from .naming import VIDEO_EXTS, canonical_stem, load_json, save_json, ts

STAGES = ("待处理", "提取音频", "转写中", "AI校对", "总结提炼", "生成文档", "完成")
TERMINAL = ("done", "failed", "canceled")


class TaskCanceled(Exception):
    """用户取消, 用于打断阶段流程"""


def _is_oom(e: Exception) -> bool:
    """判断是否为显存/内存不足, 用于决定是否回退 CPU 重试"""
    msg = str(e).lower()
    keys = ("out of memory", "outofmemory", "cuda error", "cublas",
            "insufficient memory", "allocation failed", "cudnn")
    return any(k in msg for k in keys)


def _norm_created(v) -> float:
    """历史任务的 created 是字符串("2026-08-22 09:01:00"), 新任务是时间戳, 统一成 float"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return time.mktime(time.strptime(v, fmt))
            except ValueError:
                continue
    return 0.0


class Worker:
    def __init__(self, dirs: dict, settings: dict, on_settings_saved=None):
        self.dirs = dirs
        self.settings = settings
        self.on_settings_saved = on_settings_saved
        self.log = applog.get()
        self._lock = threading.Lock()
        self._tasks = load_json(dirs["tasks"], [])
        for t in self._tasks:
            t.setdefault("is_copy", False)
            t.setdefault("cancel", False)
            t["created"] = _norm_created(t.get("created"))
            if t.get("status") in ("running", "queued"):
                t["status"] = "interrupted"
                t["error"] = "程序中断, 可重试"
        self._stop = False
        self._worker = None

    # ---------- 位置 ----------
    @property
    def dir_video(self) -> Path:
        return self.dirs["video"]

    @property
    def dir_out(self) -> Path:
        return self.dirs["docs"]

    def relocate(self, dirs: dict):
        """工作目录切换后刷新路径"""
        self.dirs = dirs

    # ---------- 配置 ----------
    def save_settings(self, new: dict):
        with self._lock:
            self.settings = new
        if self.on_settings_saved:
            self.on_settings_saved(new)

    # ---------- 任务管理 ----------
    def _save(self):
        save_json(self.dirs["tasks"], self._tasks)

    def list_tasks(self):
        with self._lock:
            return [dict(t) for t in self._tasks]

    def get_task(self, task_id: str):
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None

    def add_paths(self, paths: list[str], is_copy: bool = False) -> list[dict]:
        added = []
        with self._lock:
            for p in paths:
                vp = Path(p)
                if not vp.exists() or vp.suffix.lower() not in VIDEO_EXTS:
                    continue
                task = {"id": "t_" + uuid.uuid4().hex[:10],
                        "video": vp.name, "video_path": str(vp), "is_copy": is_copy,
                        "stem": "", "created": time.time(),
                        "status": "queued", "stage": STAGES[0], "progress": 0.0,
                        "error": None, "outputs": {}, "doubtful": [],
                        "meta": {}, "cancel": False}
                self._tasks.append(task)
                added.append(dict(task))
            self._save()
        self._wake()
        return added

    def retry(self, task_id: str):
        with self._lock:
            t = self.get_task(task_id)
            if t:
                t.update(status="queued", stage=STAGES[0], progress=0.0,
                         error=None, cancel=False)
                self._save()
        self._wake()

    def cancel(self, task_id: str):
        with self._lock:
            t = self.get_task(task_id)
            if not t:
                return
            t["cancel"] = True
            if t["status"] in ("queued", "interrupted"):
                t["status"] = "canceled"
                t["stage"] = "已取消"
            elif t["status"] == "running":
                t["cancel_stage"] = t.get("stage")   # 记下取消时所处阶段
                t["stage"] = "正在取消"
            self._save()

    def delete(self, task_id: str):
        with self._lock:
            self._tasks = [t for t in self._tasks if t["id"] != task_id]
            self._save()

    # ---------- 状态更新 ----------
    def _update(self, task, status=None, stage=None, progress=None, error=None,
                meta=None, save=True):
        with self._lock:
            if status:
                task["status"] = status
            if stage:
                task["stage"] = stage
            if progress is not None:
                task["progress"] = round(progress, 3)
            if error is not None:
                task["error"] = error
            if meta:
                task["meta"].update(meta)
            if save:
                self._save()

    def _check_cancel(self, task):
        if task.get("cancel"):
            raise TaskCanceled()

    def _progress_cb(self, task, base: float = 0.0, span: float = 1.0):
        """把子任务 0~1 的进度映射到整体区间的 base ~ base+span, 并节流写盘"""
        last = {"t": 0.0}

        def cb(p):
            self._check_cancel(task)
            now = time.time()
            if now - last["t"] > 0.4 or p >= 1:
                last["t"] = now
                self._update(task, progress=base + max(0.0, min(1.0, p)) * span,
                             save=True)
        return cb

    def _bump(self, task, value: float):
        """只增不减地推进进度(供心跳使用, 避免与真实回调互相覆盖)"""
        with self._lock:
            if value > (task.get("progress") or 0):
                task["progress"] = round(min(0.99, value), 3)
                self._save()

    def _heartbeat(self, task, base: float, span: float, est_seconds: float,
                   stop: threading.Event):
        """批量推理不会边跑边吐结果, 靠时间估算让进度条动起来"""
        t0 = time.time()
        while not stop.wait(1.0):
            if task.get("cancel"):
                return
            elapsed = time.time() - t0
            frac = min(0.92, elapsed / max(est_seconds, 1.0))
            self._bump(task, base + span * frac)

    # ---------- 执行 ----------
    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def stop(self):
        self._stop = True

    def _wake(self):
        self.start()

    def _loop(self):
        while not self._stop:
            task = None
            with self._lock:
                for t in self._tasks:
                    if t["status"] == "queued":
                        task = t
                        break
            if task is None:
                time.sleep(1)
                continue
            try:
                self._run(task)
            except (TaskCanceled, engine.Canceled, proofread.Canceled):
                self._finalize_canceled(task)
            except Exception as e:
                self.log.exception("任务失败: %s", task.get("video"))
                self._update(task, status="failed", stage="失败", error=str(e)[:500])
            time.sleep(0.3)

    def _finalize_canceled(self, task):
        failed_stage = task.get("cancel_stage") or task.get("stage") or "处理"
        self._update(task, status="canceled", stage="已取消",
                     error=f"已在「{failed_stage}」阶段取消")
        self._cleanup_intermediate(task)
        self.log.info("任务已取消: %s", task.get("video"))

    def _run(self, task: dict):
        self._update(task, status="running", error=None, stage=STAGES[0])
        s = self.settings
        video = Path(task["video_path"])
        if not video.exists():
            raise RuntimeError(f"源文件不存在: {video.name}")
        stem, mtime = canonical_stem(video)
        task["stem"] = stem
        out_dir = self.dir_out / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = self.dirs["audio"] / f"{stem}.wav"
        mp3 = out_dir / f"{stem}_音频.mp3"
        meta = {"video": video.name, "mtime": mtime.strftime("%Y-%m-%d %H:%M")}
        hw = engine.detect_hardware()
        tr = s.get("transcribe", {})
        model_name, device, compute, batch = engine.pick_tier(
            hw, tr.get("tier", "auto"), tr.get("device", "auto"))
        seg_cache = self.dirs["text"] / f"{stem}.segments.json"
        cache_key = f"{model_name}({device})"

        self._check_cancel(task)

        # 阶段缓存: 同文件同模型 -> 复用转写结果, 省去重复识别
        cached = None
        if seg_cache.exists():
            try:
                c = load_json(seg_cache)
                if c.get("meta", {}).get("model") == cache_key and c.get("segments"):
                    cached = c
            except Exception:
                cached = None

        if cached:
            segments, total = cached["segments"], cached["meta"].get("duration", 0)
            meta.update({k: v for k, v in cached["meta"].items() if k != "model"})
            meta["model"] = cache_key
            meta["duration"] = total
            self._update(task, stage="转写复用", progress=1.0)
            self.log.info("复用转写缓存: %s", stem)
        else:
            # 1. 提取音频 (进度 3% ~ 8%)
            self._update(task, stage=STAGES[1], progress=0.03)
            self._check_cancel(task)
            last_t = {"t": 0.0}

            def extract_cb(p):
                self._check_cancel(task)
                now = time.time()
                if now - last_t["t"] > 0.4 or p >= 1:
                    last_t["t"] = now
                    self._update(task, progress=0.03 + p * 0.05, save=True)

            duration, _ = engine.extract_audio(
                video, wav, mp3,
                should_cancel=lambda: bool(task.get("cancel")),
                progress_cb=extract_cb)
            meta["duration"] = duration
            self._check_cancel(task)

            # 2. 转写 (整体进度 8% ~ 70%)
            self._update(task, stage=STAGES[2], progress=0.08)
            cpu_threads = 0
            if device == "cpu":
                cpu_threads = max(2, (os.cpu_count() or 4) - 2)
            model = engine.load_model(model_name, device, compute,
                                      local_dir=self._models_dir(),
                                      cpu_threads=cpu_threads)
            cb = self._progress_cb(task, base=0.08, span=0.62)
            # 批量推理不吐中间结果, 用时间估算驱动进度条;
            # 估算按 8 倍实时(GPU large-v3 经验值), 真实进度到达时自动接管
            stop_hb = threading.Event()
            # GPU large-v3 约 8 倍实时, CPU 约 1.2 倍实时; 估算只是让进度条平滑
            speed = 8.0 if device == "cuda" else 1.2
            est = max(8.0, float(meta.get("duration") or 0) / speed)
            threading.Thread(target=self._heartbeat,
                             args=(task, 0.08, 0.62, est, stop_hb),
                             daemon=True).start()
            try:
                segments, total = engine.transcribe(
                    wav, model, tr.get("language", "zh"),
                    tr.get("hotwords", ""), cb, batch_size=batch)
            except Exception as e:
                # 显存不足: 退回 CPU 重跑, 不直接判失败
                if device == "cuda" and _is_oom(e):
                    self.log.warning("GPU 显存不足, 回退 CPU: %s", str(e)[:120])
                    meta["gpu_fallback"] = "显存不足, 已回退 CPU"
                    device, compute, batch = "cpu", "int8", 0
                    cpu_threads = max(2, (os.cpu_count() or 4) - 2)
                    model = engine.load_model(model_name, "cpu", "int8",
                                              local_dir=self._models_dir(),
                                              cpu_threads=cpu_threads)
                    segments, total = engine.transcribe(
                        wav, model, tr.get("language", "zh"),
                        tr.get("hotwords", ""), cb, batch_size=0)
                else:
                    raise
            finally:
                stop_hb.set()
            meta["model"] = cache_key
            meta["duration"] = total
            # 立即落盘: 即使后续步骤失败也不用重跑识别 (meta 必须带 model,
            # 否则下次启动缓存判定失败会白跑一遍)
            save_json(seg_cache, {"stem": stem, "meta": meta,
                                  "segments": segments, "doubtful": []})
            if not segments:
                self._finish(task, stem, out_dir, mp3, segments, total, meta, None, [])
                return

        self._check_cancel(task)

        # 3. AI 校对
        api_key = (s["api"].get("api_key") or "").strip()
        use_proof = api_key and s.get("output", {}).get("proofread", True)
        corrected = None
        llm_doubts = []
        if use_proof:
            self._update(task, stage=STAGES[3], progress=0.75)
            try:
                corrected, llm_doubts = proofread.proofread(
                    segments, total, s, s["transcribe"].get("hotwords", ""),
                    should_cancel=lambda: bool(task.get("cancel")))
            except TaskCanceled:
                raise
            except Exception as e:
                meta["proofread_error"] = str(e)[:150]
                self.log.warning("AI 校对失败: %s", e)

        self._check_cancel(task)

        # 4. 生成文档
        self._update(task, stage=STAGES[5], progress=0.9)
        self._finish(task, stem, out_dir, mp3, segments, total, meta,
                     corrected, llm_doubts, llm_api_ok=bool(api_key))

    def _models_dir(self) -> Path:
        """模型目录: 优先程序目录(安装包自带), 其次数据目录(用户下载)"""
        from . import paths as _paths
        return _paths.models_dir()

    def _finish(self, task, stem, out_dir, mp3, segments, total, meta,
                corrected, llm_doubts, llm_api_ok=False):
        fmt_ts = ts
        doubtful = []
        for seg in segments:
            if seg.get("doubt"):
                doubtful.append({"t": fmt_ts(seg["start"], total),
                                 "text": seg["text"][:80],
                                 "source": "语音置信度低"})
        for d in llm_doubts:
            t = d.split("]", 1)[0].strip() if d.startswith("[") else ""
            txt = d.split("]", 1)[1].strip() if d.startswith("[") else d
            doubtful.append({"t": t.lstrip("["), "text": txt[:80], "source": "AI校对"})

        # 转写稿 txt
        lines = [f"# 转录稿: {stem}", f"视频: {meta.get('video')}",
                 f"录制时间: {meta.get('mtime')}",
                 f"时长: {fmt_ts(total, total)}", f"模型: {meta.get('model')}", "---"]
        body = []
        for seg in segments:
            t = fmt_ts(seg["start"], total)
            mark = " [存疑]" if seg.get("doubt") else ""
            body.append(f"[{t}] {seg['text']}{mark}")
        lines += body or ["(无有效语音内容)"]
        lines += ["---", f"## 存疑片段(共 {len(doubtful)} 处)"]
        lines += [f"{i+1}. [{d['t']}] {d['text']}" for i, d in enumerate(doubtful)] or ["无"]
        txt_path = self.dirs["text"] / f"{stem}.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        save_json(self.dirs["text"] / f"{stem}.segments.json",
                  {"stem": stem, "meta": meta, "segments": segments,
                   "doubtful": doubtful})

        rec_text = corrected if corrected else _segments_text(segments, total)
        rec = docgen.build_record_docx(
            stem, meta, rec_text, segments, doubtful,
            out_dir / f"{stem}_文字记录.docx")

        # 总结提炼 (受开关控制)
        sum_doc = None
        if llm_api_ok and self.settings.get("output", {}).get("summary", True):
            self._update(task, stage=STAGES[4], progress=0.95)
            try:
                md = proofread.summarize(
                    corrected or _segments_text(segments, total), self.settings)
                sum_doc = docgen.md_to_docx(md, out_dir / f"{stem}_总结提炼.docx")
            except Exception as e:
                meta["summary_error"] = str(e)[:150]
                self.log.warning("总结生成失败: %s", e)

        srt = docgen.build_srt(segments, total, out_dir / f"{stem}.srt")

        task["outputs"] = {"record": str(rec), "audio": str(mp3),
                           "summary": str(sum_doc) if sum_doc else None,
                           "srt": str(srt), "txt": str(txt_path),
                           "folder": str(out_dir)}
        task["doubtful"] = doubtful
        self._update(task, status="done", stage=STAGES[6], progress=1.0, meta=meta)
        self._cleanup_intermediate(task)
        self.log.info("转写完成: %s -> %s", stem, out_dir)

    def _cleanup_intermediate(self, task):
        """收尾清理: 中间 wav 总是删; 不保留源文件时再删上传副本与 mp3"""
        stem = task.get("stem") or ""
        if stem:
            wav = self.dirs["audio"] / f"{stem}.wav"
            try:
                if wav.exists():
                    wav.unlink()
            except OSError:
                pass
        keep = self.settings.get("output", {}).get("keep_source", True)
        if keep:
            return
        outs = task.get("outputs") or {}
        mp3 = outs.get("audio")
        if mp3 and Path(mp3).exists():
            try:
                Path(mp3).unlink()
            except OSError:
                pass
        if task.get("is_copy"):
            vp = Path(task.get("video_path", ""))
            try:
                if vp.exists() and vp.parent == self.dir_video:
                    vp.unlink()
            except OSError:
                pass
            outs["audio"] = None
            task["outputs"] = outs


def _segments_text(segments: list, total: float) -> str:
    lines = []
    for seg in segments:
        t = ts(seg["start"], total)
        mark = " [存疑]" if seg.get("doubt") else ""
        lines.append(f"[{t}] {seg['text']}{mark}")
    return "\n".join(lines)
