# -*- coding: utf-8 -*-
"""转写引擎: 硬件自检、模型档位、音频提取、Whisper 转写"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import applog
from .naming import VIDEO_EXTS

TIERS = ["auto", "large-v3", "distil-large-v3", "medium", "small", "tiny"]
LOW_PROB_THRESHOLD = -1.0  # 平均对数概率低于此值视为"听不清"

# 国内网络: HuggingFace 直连不通时自动切换镜像
MIRROR = "https://hf-mirror.com"

_hw_cache = {}


class Canceled(Exception):
    """外部取消"""


def ffmpeg_path() -> str:
    """优先用软件自带的 ffmpeg (随包分发), 否则用系统 PATH 里的"""
    if getattr(sys, "frozen", False):
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        cand = Path(sys.executable).resolve().parent / exe
        if cand.exists():
            return str(cand)
    return shutil.which("ffmpeg") or "ffmpeg"


def detect_hardware(force: bool = False) -> dict:
    """硬件自检, 结果缓存(每 60 秒内不重复探测)"""
    import time
    if not force and _hw_cache and time.time() - _hw_cache.get("_t", 0) < 60:
        return {k: v for k, v in _hw_cache.items() if k != "_t"}
    hw = {"cuda": False, "cores": os.cpu_count() or 4, "ram_gb": 8,
          "gpu_name": "", "vram_gb": 0.0}
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            hw["cuda"] = True
            hw["gpu_name"] = "NVIDIA GPU"
    except Exception:
        pass

    # 显存: 优先 pynvml, 没有就用 nvidia-smi, 都没有则留 0(按保守策略处理)
    if hw["cuda"] and not hw["vram_gb"]:
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            hw["gpu_name"] = name
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            hw["vram_gb"] = round(mem.total / 1024 ** 3, 1)
            pynvml.nvmlShutdown()
        except Exception:
            pass
    if hw["cuda"] and not hw["vram_gb"]:
        try:
            import subprocess
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10)
            line = (out.stdout or "").strip().splitlines()[0]
            name, mem_mb = [x.strip() for x in line.split(",")[:2]]
            hw["gpu_name"] = name
            hw["vram_gb"] = round(float(mem_mb) / 1024, 1)
        except Exception:
            pass

    try:
        import psutil
        hw["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3)
    except Exception:
        pass
    hw["_t"] = time.time()
    _hw_cache.update(hw)
    return {k: v for k, v in hw.items() if k != "_t"}


def pick_tier(hw: dict, tier: str, device_pref: str = "auto") -> tuple:
    """返回 (模型名, 设备, 计算类型, 批量大小)

    批量大小 > 0 时走 faster-whisper 的批量推理, GPU 上吞吐通常提升 2~4 倍;
    CPU 上批量收益有限且更吃内存, 保持逐段推理(batch=0)。
    """
    use_cuda = bool(hw.get("cuda")) and device_pref != "cpu"
    if device_pref == "cuda" and not hw.get("cuda"):
        use_cuda = False
        applog.get().warning("设置为仅 GPU, 但未检测到可用的 CUDA 设备, 回退 CPU")

    vram = float(hw.get("vram_gb") or 0)

    if not use_cuda:
        if tier != "auto":
            return tier, "cpu", "int8", 0
        if hw.get("cores", 0) >= 8 and hw.get("ram_gb", 0) >= 16:
            return "large-v3", "cpu", "int8", 0
        if hw.get("ram_gb", 0) >= 8:
            return "distil-large-v3", "cpu", "int8", 0
        if hw.get("ram_gb", 0) >= 6:
            return "medium", "cpu", "int8", 0
        return "small", "cpu", "int8", 0

    # ---- GPU ----
    # 显存未知时按 6GB 保守估计
    est = vram if vram > 0 else 6.0
    if tier == "auto":
        model = "large-v3" if est >= 3.5 else "medium"
    else:
        model = tier

    # 大模型 fp16 常驻约 3GB; 显存紧张改用 int8_float16
    compute = "float16" if est >= 6.0 else "int8_float16"
    if model in ("medium", "small", "tiny", "distil-large-v3") and est < 3.0:
        compute = "int8_float16"

    if est >= 10:
        batch = 16
    elif est >= 6:
        batch = 8
    elif est >= 4:
        batch = 4
    else:
        batch = 1
    return model, "cuda", compute, batch


def _bypass_registry_proxy():
    """Windows 注册表可能残留失效的系统代理, 导致下载失败; 统一绕过"""
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")


def _ensure_cuda_dlls():
    """把 nvidia 运行时库加入动态库搜索路径, 避免 ctranslate2 找不到 cublas。

    Windows 用 os.add_dll_directory + PATH; Linux/mac 用 LD_LIBRARY_PATH
    并预加载(libcublas 等是 ctranslate2 运行时 dlopen 的)。
    """
    if os.name != "nt":
        if sys.platform.startswith("linux"):
            dirs = []
            bases = []
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                bases.append(Path(meipass))
            try:
                import site
                bases += [Path(b) for b in site.getsitepackages()]
            except Exception:
                pass
            for base in bases:
                nv = base / "nvidia"
                if not nv.is_dir():
                    continue
                for sub in nv.iterdir():
                    for name in ("lib", "bin"):
                        d = sub / name
                        if d.is_dir():
                            dirs.append(str(d))
            if dirs:
                cur = os.environ.get("LD_LIBRARY_PATH", "")
                missing = [d for d in dirs if d not in cur.split(":")]
                if missing:
                    os.environ["LD_LIBRARY_PATH"] = ":".join(missing + ([cur] if cur else []))
        return

    dirs = []
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass))
    try:
        import site
        bases += [Path(b) for b in site.getsitepackages()]
    except Exception:
        pass
    for base in bases:
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for sub in nv.iterdir():
            b = sub / "bin"
            if b.is_dir():
                dirs.append(str(b))
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
    if dirs:
        env_path = os.environ.get("PATH", "")
        missing = [d for d in dirs if d.lower() not in env_path.lower()]
        if missing:
            os.environ["PATH"] = os.pathsep.join(missing) + os.pathsep + env_path


_ensure_cuda_dlls()


def load_model(model_name: str, device: str, compute_type: str,
               local_dir: Path | None = None, cpu_threads: int = 0):
    """加载模型: 优先本地 models/ 目录(随包分发), 否则下载(直连失败换镜像)

    cpu_threads 必须传进构造函数 —— WhisperModel.transcribe() 不接受该参数。
    """
    from faster_whisper import WhisperModel
    if device == "cuda":
        _ensure_cuda_dlls()

    kwargs = {"device": device, "compute_type": compute_type}
    if device == "cuda":
        kwargs["device_index"] = 0
    if cpu_threads:
        kwargs["cpu_threads"] = cpu_threads

    if local_dir is not None:
        local = Path(local_dir) / model_name
        if local.is_dir():
            return WhisperModel(str(local), **kwargs)
    _bypass_registry_proxy()
    attempts = [None, MIRROR, MIRROR]
    last_err = None
    for i, ep in enumerate(attempts):
        if ep:
            os.environ["HF_ENDPOINT"] = ep
        try:
            return WhisperModel(model_name, **kwargs)
        except Exception as e:
            last_err = e
            applog.get().warning("模型加载失败(第%d次): %s", i + 1, str(e)[:120])
            if i < len(attempts) - 1:
                print(f"  模型加载失败(第{i+1}次): {str(e)[:100]}\n  重试中...")
    raise RuntimeError(f"模型加载失败: {str(last_err)[:150]}")


def _run_ffmpeg(cmd: list, should_cancel=None, on_progress=None,
                duration: float = 0.0):
    """跑 ffmpeg, 支持取消与真实进度。

    注意: 不能把 stderr 接到 PIPE 后只 wait —— ffmpeg 会持续往 stderr 写进度,
    管道缓冲区写满后 ffmpeg 阻塞, 调用方永远等不到进程退出(表现为进度卡在几%)。
    这里把 stderr 重定向到临时文件, 同时用 -progress pipe:1 读取 stdout 拿进度。
    """
    import tempfile
    err_file = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=err_file, bufsize=1, text=True, encoding="utf-8",
            errors="replace")
        while True:
            if should_cancel and should_cancel():
                proc.kill()
                proc.wait()
                raise Canceled()
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            if on_progress and duration > 0:
                key, _, val = line.strip().partition("=")
                if key == "out_time_ms":
                    try:
                        sec = int(val) / 1_000_000
                        on_progress(max(0.0, min(0.99, sec / duration)))
                    except ValueError:
                        pass
        proc.wait()
        if on_progress:
            on_progress(1.0)
        if proc.returncode != 0:
            err_file.seek(0)
            msg = err_file.read().decode("utf-8", "replace")[-400:]
            raise RuntimeError(f"ffmpeg 失败 (code {proc.returncode}): {msg}")
        return proc.returncode
    finally:
        try:
            err_file.close()
        except Exception:
            pass


def probe_duration(path: Path) -> float:
    """读取媒体时长(秒), 失败返回 0"""
    try:
        r = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        for line in (r.stderr or "").splitlines():
            if "Duration:" in line:
                d = line.split("Duration:")[1].split(",")[0].strip()
                hh, mm, ss = d.split(":")
                return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        pass
    return 0.0


def extract_audio(video: Path, wav_path: Path, mp3_path: Path,
                  should_cancel=None, progress_cb=None) -> tuple[float, str]:
    """提取 16kHz 单声道 wav(转写用) + mp3(交付用); 返回 (时长秒, 视频文件名)

    progress_cb: 0~1, 覆盖两个文件的转换过程
    """
    ffmpeg = ffmpeg_path()
    total = probe_duration(video)
    # 两段任务各占一半进度
    def sub_cb(base):
        def cb(p):
            if progress_cb:
                progress_cb(min(0.99, base + p * 0.5))
        return cb

    _run_ffmpeg([ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(video),
                 "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                 "-progress", "pipe:1", str(wav_path)],
                should_cancel, sub_cb(0.0), total)
    _run_ffmpeg([ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(video),
                 "-vn", "-c:a", "libmp3lame", "-q:a", "3",
                 "-progress", "pipe:1", str(mp3_path)],
                should_cancel, sub_cb(0.5), total)
    dur = total or probe_duration(wav_path)
    if progress_cb:
        progress_cb(1.0)
    return dur, video.name


def transcribe(wav_path: Path, model, language: str, hotwords: str,
               progress_cb=None, batch_size: int = 0):
    """转写 wav -> 分段列表; 进度按已识别段的时间戳估算 (0~1)

    batch_size > 0 时使用 faster-whisper 的批量推理(GPU 上吞吐提升明显),
    批量不可用或失败时自动退回逐段推理。
    """
    lang = None if language in ("auto", "", None) else language
    kw = {"language": lang, "vad_filter": True, "beam_size": 5}
    if hotwords.strip():
        kw["hotwords"] = hotwords.strip()

    segments = info = None
    if batch_size and batch_size > 0:
        try:
            from faster_whisper import BatchedInferencePipeline
            pipe = BatchedInferencePipeline(model=model)
            segments, info = pipe.transcribe(str(wav_path),
                                             batch_size=batch_size, **kw)
        except Exception as e:
            applog.get().warning("批量推理不可用, 回退逐段: %s", str(e)[:120])
            segments = None

    if segments is None:
        try:
            segments, info = model.transcribe(str(wav_path), **kw)
        except TypeError:
            kw.pop("hotwords", None)  # 旧版本不支持热词
            segments, info = model.transcribe(str(wav_path), **kw)

    total = info.duration
    result = []
    last_p = 0.0
    for seg in segments:
        text = seg.text.strip()
        if text:
            doubt = seg.avg_logprob < LOW_PROB_THRESHOLD
            result.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                           "text": text, "doubt": doubt,
                           "doubt_reason": "语音置信度低" if doubt else ""})
        if progress_cb and total > 0:
            p = min(0.99, seg.end / total)
            if p - last_p >= 0.02 or p >= 0.99:
                last_p = p
                progress_cb(p)
    if progress_cb:
        progress_cb(1.0)
    return result, total
