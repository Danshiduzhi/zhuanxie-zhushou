# -*- coding: utf-8 -*-
"""任务队列与持久化: 单线程顺序处理, 状态落盘, 支持断点续跑"""
import json
import threading
import time
import uuid
from pathlib import Path

from . import diarize, docgen, engine, proofread
from .naming import VIDEO_EXTS, canonical_stem, load_json, save_json, ts

STATUS = ("queued", "running", "done", "failed", "interrupted", "canceled")
STAGES = ("待处理", "提取音频", "转写中", "说话人区分", "AI校对", "生成文档", "完成")


def _empty_settings():
    return {
        "api": {"provider": "deepseek", "base_url": "https://api.deepseek.com/v1",
                "api_key": "", "model": "deepseek-chat"},
        "transcribe": {"tier": "auto", "language": "zh", "hotwords": ""},
        "diarize": {"enabled": True, "hf_token": ""},
        "output_dir": "04_文档",
    }


class Worker:
    def __init__(self, base: Path):
        self.base = base
        self.dir_video = base / "01_视频"
        self.dir_audio = base / "02_音频"
        self.dir_txt = base / "03_转写"
        self.dir_out = base / "04_文档"
        self.data_dir = base / "data"
        self.tasks_file = self.data_dir / "tasks.json"
        for d in (self.dir_video, self.dir_audio, self.dir_txt,
                  self.dir_out, self.data_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._settings = load_json(base / "config.json", _empty_settings())
        self._settings.setdefault("api", _empty_settings()["api"])
        self._settings.setdefault("transcribe", _empty_settings()["transcribe"])
        self._settings.setdefault("diarize", _empty_settings()["diarize"])
        self._settings.setdefault("output_dir", "04_文档")
        self._lock = threading.Lock()
        self._tasks = load_json(self.tasks_file, [])
        for t in self._tasks:
            if t.get("status") in ("running", "queued"):
                t["status"] = "interrupted"
                t["error"] = "程序中断, 可重试"
        self._stop = False
        self._worker = None

    # ---------- 配置 ----------
    @property
    def settings(self) -> dict:
        return self._settings

    def save_settings(self, new: dict):
        with self._lock:
            self._settings = new
        save_json(self.base / "config.json", new)

    # ---------- 任务管理 ----------
    def _save(self):
        """写 tasks.json 加文件锁, 防止多进程互相覆盖"""
        try:
            import msvcrt
            lock = open(self.data_dir / "tasks.lock", "w")
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                save_json(self.tasks_file, self._tasks)
            finally:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                lock.close()
        except (ImportError, OSError):
            save_json(self.tasks_file, self._tasks)

    def list_tasks(self):
        with self._lock:
            return [dict(t) for t in self._tasks]

    def get_task(self, task_id: str):
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None

    def add_paths(self, paths: list[str]) -> list[dict]:
        added = []
        with self._lock:
            for p in paths:
                vp = Path(p)
                if not vp.exists() or vp.suffix.lower() not in VIDEO_EXTS:
                    continue
                task = {"id": "t_" + uuid.uuid4().hex[:10],
                        "video": vp.name, "video_path": str(vp), "stem": "",
                        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
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
            if t and t["status"] in ("queued", "running"):
                t["cancel"] = True
                if t["status"] == "queued":
                    t["status"] = "canceled"
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

    def _progress_cb(self, task):
        last = {"t": 0.0}

        def cb(p):
            now = time.time()
            if now - last["t"] > 0.4 or p >= 1:
                last["t"] = now
                self._update(task, progress=p, save=True)
        return cb

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
            except Exception as e:
                self._update(task, status="failed", stage="失败", error=str(e)[:500])
            time.sleep(0.5)

    def _run(self, task: dict):
        self._update(task, status="running", error=None)
        s = self._settings
        video = Path(task["video_path"])
        stem, mtime = canonical_stem(video)
        task["stem"] = stem
        out_dir = self.dir_out / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = self.dir_audio / f"{stem}.wav"
        mp3 = out_dir / f"{stem}_音频.mp3"
        meta = {"video": video.name,
                "mtime": mtime.strftime("%Y-%m-%d %H:%M")}
        hw = engine.detect_hardware()
        model_name, device, compute = engine.pick_tier(hw, s["transcribe"]["tier"])
        seg_cache = self.dir_txt / f"{stem}.segments.json"

        # 阶段缓存: 转写已完成且模型配置未变 -> 复用, 省去重复转写
        cached = None
        if seg_cache.exists():
            try:
                c = load_json(seg_cache)
                if c.get("meta", {}).get("model") == f"{model_name}({device})":
                    cached = c
            except Exception:
                cached = None

        if cached:
            segments, total = cached["segments"], cached["meta"]["duration"]
            self._update(task, stage="转写复用", progress=1.0)
        else:
            # 1. 提取音频
            self._update(task, stage=STAGES[1], progress=0.05)
            duration, _ = engine.extract_audio(video, wav, mp3)
            meta["duration"] = duration

            # 2. 转写 (CPU 模式限线程, 避免打满所有核导致窗口卡顿)
            self._update(task, stage=STAGES[2], progress=0.1)
            model = engine.load_model(model_name, device, compute,
                                      local_dir=self.base / "models")
            cpu_threads = None
            if device == "cpu":
                cores = __import__("os").cpu_count() or 4
                cpu_threads = max(2, cores - 2)
            segments, total = engine.transcribe(
                wav, model, s["transcribe"].get("language", "zh"),
                s["transcribe"].get("hotwords", ""), self._progress_cb(task),
                cpu_threads=cpu_threads)
            meta.update(model=f"{model_name}({device})")
            if not segments:
                self._finish(task, stem, out_dir, wav, mp3, segments, total, meta,
                             None, [])
                return
            # 立即落盘, 供后续复用
            save_json(self.dir_txt / f"{stem}.segments.json", {
                "stem": stem, "meta": meta, "segments": segments, "doubtful": []})

        # 3. 说话人区分 (未配置 Token 时自动跳过; 已有标签则复用)
        speakers = 0
        has_speakers = bool(segments) and all(seg.get("speaker") for seg in segments)
        if diarize.enabled(s):
            if has_speakers:
                speakers = len({seg["speaker"] for seg in segments})
                meta["speakers"] = speakers
            else:
                self._update(task, stage=STAGES[3])
                try:
                    spans = diarize.run(str(wav), s, self._progress_cb(task))
                    if spans:
                        speakers = _assign_speakers(segments, spans)
                        meta["speakers"] = speakers
                except Exception as e:
                    meta["speakers_error"] = str(e)[:120]

        # 4. AI 校对
        corrected = None
        llm_doubts = []
        api_key = (s["api"].get("api_key") or "").strip()
        if api_key:
            self._update(task, stage=STAGES[4])
            try:
                corrected, llm_doubts = proofread.proofread(
                    segments, total, s, s["transcribe"].get("hotwords", ""))
            except Exception as e:
                meta["proofread_error"] = str(e)[:150]

        # 5. 生成文档 (三件套 + 字幕)
        self._update(task, stage=STAGES[5], progress=0.9)
        self._finish(task, stem, out_dir, wav, mp3, segments, total, meta,
                     corrected, llm_doubts, llm_api_ok=bool(api_key))

    def _finish(self, task, stem, out_dir, wav, mp3, segments, total, meta,
                corrected, llm_doubts, llm_api_ok=False):
        from .naming import ts as fmt_ts
        # 存疑清单: ASR 低置信度 + LLM 语义疑问
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

        # 转写稿 (txt + segments.json 留档)
        lines = [f"# 转录稿: {stem}", f"视频: {meta.get('video')}",
                 f"录制时间: {meta.get('mtime')}",
                 f"时长: {fmt_ts(total, total)}", f"模型: {meta.get('model')}",
                 "---"]
        body = []
        for seg in segments:
            t = fmt_ts(seg["start"], total)
            tag = f" [{seg['speaker']}]" if seg.get("speaker") else ""
            mark = " [存疑]" if seg.get("doubt") else ""
            body.append(f"[{t}]{tag} {seg['text']}{mark}")
        lines += body or ["(无有效语音内容)"]
        lines += ["---", f"## 存疑片段(共 {len(doubtful)} 处)"]
        lines += [f"{i+1}. [{d['t']}] {d['text']}" for i, d in enumerate(doubtful)] or ["无"]
        txt_path = self.dir_txt / f"{stem}.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        save_json(self.dir_txt / f"{stem}.segments.json", {
            "stem": stem, "meta": meta, "segments": segments, "doubtful": doubtful})

        # 文字记录 Word: 校对成功用校对稿(时间戳对齐, 不丢行), 否则用原文
        rec_text = corrected if corrected else _segments_text(segments, total)
        rec = docgen.build_record_docx(
            stem, meta, rec_text, segments, doubtful,
            out_dir / f"{stem}_文字记录.docx")

        # 总结提炼 Word + 字幕
        sum_doc = None
        if llm_api_ok:
            try:
                md = proofread.summarize(
                    corrected or _segments_text(segments, total), self._settings)
                sum_doc = docgen.md_to_docx(md, out_dir / f"{stem}_总结提炼.docx")
            except Exception as e:
                meta["summary_error"] = str(e)[:150]
        srt = docgen.build_srt(segments, total, out_dir / f"{stem}.srt")

        task["outputs"] = {"record": str(rec), "audio": str(mp3),
                           "summary": str(sum_doc) if sum_doc else None,
                           "srt": str(srt), "txt": str(txt_path)}
        task["doubtful"] = doubtful
        self._update(task, status="done", stage=STAGES[6], progress=1.0,
                     meta=meta)


def _segments_text(segments: list, total: float) -> str:
    from .naming import ts as fmt_ts
    lines = []
    for seg in segments:
        t = fmt_ts(seg["start"], total)
        tag = f" [{seg['speaker']}]" if seg.get("speaker") else ""
        mark = " [存疑]" if seg.get("doubt") else ""
        lines.append(f"[{t}]{tag} {seg['text']}{mark}")
    return "\n".join(lines)


def _assign_speakers(segments: list, spans: list) -> int:
    """按时间重叠把说话人标签映射到转写分段"""
    import bisect
    starts = [sp[0] for sp in spans]
    n_speakers = 0
    labels = {}
    for seg in segments:
        i = bisect.bisect_right(starts, seg["start"]) - 1
        sp = spans[i] if 0 <= i < len(spans) else None
        if sp and sp[1] >= seg["start"]:
            lab = sp[2]
            if lab not in labels:
                labels[lab] = chr(ord("A") + len(labels))
            seg["speaker"] = labels[lab]
    return len(labels)
