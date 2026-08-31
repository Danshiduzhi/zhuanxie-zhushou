# -*- coding: utf-8 -*-
"""转写引擎: 硬件自检、模型档位、音频提取、Whisper 转写"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .naming import VIDEO_EXTS

TIERS = ["auto", "large-v3", "distil-large-v3", "medium", "small", "tiny"]
LOW_PROB_THRESHOLD = -1.0  # 平均对数概率低于此值视为"听不清"

# 国内网络: HuggingFace 直连不通时自动切换镜像
MIRROR = "https://hf-mirror.com"


def ffmpeg_path() -> str:
    """优先用软件自带的 ffmpeg (随包分发), 否则用系统 PATH 里的"""
    if getattr(sys, "frozen", False):
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        cand = Path(sys.executable).resolve().parent / exe
        if cand.exists():
            return str(cand)
    return shutil.which("ffmpeg") or "ffmpeg"


def detect_hardware() -> dict:
    hw = {"cuda": False, "cores": os.cpu_count() or 4, "ram_gb": 8}
    try:
        import ctranslate2
        hw["cuda"] = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        import psutil
        hw["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3)
    except Exception:
        pass
    return hw


def pick_tier(hw: dict, tier: str) -> tuple[str, str, str]:
    """返回 (模型名, 设备, 计算类型)"""
    cuda = hw.get("cuda")
    if tier != "auto":
        return tier, ("cuda" if cuda else "cpu"), ("float16" if cuda else "int8")
    if cuda:
        return "large-v3", "cuda", "float16"     # 有独显: 拉满准确率
    if hw.get("cores", 0) >= 8 and hw.get("ram_gb", 0) >= 16:
        return "large-v3", "cpu", "int8"         # 强 CPU(如 M 系/Mac)
    if hw.get("ram_gb", 0) >= 8:
        return "distil-large-v3", "cpu", "int8"  # 中档 CPU
    if hw.get("ram_gb", 0) >= 6:
        return "medium", "cpu", "int8"
    return "small", "cpu", "int8"                # 弱机: 保可用


def _bypass_registry_proxy():
    """Windows 注册表可能残留失效的系统代理, 导致下载失败; 统一绕过"""
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")
    # 大模型文件在镜像上较慢, 放宽读取超时(默认10秒会超时)
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")


def _ensure_cuda_dlls():
    """把 nvidia 运行时(cublas 等)加入 DLL 搜索路径, 避免找不到 cublas64_12.dll。
    必须在任何 ctranslate2 导入之前执行, 并同时写进 PATH(ctranslate2 推理时会扫 PATH)。
    支持源码环境(site-packages)与打包环境(_MEIPASS)。"""
    if os.name != "nt":
        return
    dirs = []
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass))          # PyInstaller 解包目录
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


# 模块导入时立即执行: 保证早于任何 ctranslate2 加载
_ensure_cuda_dlls()


def load_model(model_name: str, device: str, compute_type: str,
               local_dir: Path | None = None):
    """加载模型: 优先本地 models/ 目录(可随包分发), 否则下载(直连失败换镜像, 失败自动重试)"""
    from faster_whisper import WhisperModel
    if device == "cuda":
        _ensure_cuda_dlls()
    if local_dir is not None:
        local = Path(local_dir) / model_name
        if local.is_dir():
            return WhisperModel(str(local), device=device, compute_type=compute_type)
    _bypass_registry_proxy()
    attempts = [None, MIRROR, MIRROR]  # 直连 -> 镜像(两次, 容忍瞬时失败)
    for i, ep in enumerate(attempts):
        if ep:
            os.environ["HF_ENDPOINT"] = ep
        try:
            return WhisperModel(model_name, device=device, compute_type=compute_type)
        except Exception as e:
            msg = str(e)[:100]
            if i == len(attempts) - 1:
                raise RuntimeError(f"模型加载失败: {msg}") from e
            print(f"  模型加载失败(第{i+1}次): {msg}\n  重试中...")


def extract_audio(video: Path, wav_path: Path, mp3_path: Path) -> tuple[float, str]:
    """提取 16kHz 单声道 wav(转写用) + 原音质 mp3(交付用); 返回 (时长秒, 视频文件名)"""
    ffmpeg = ffmpeg_path()

    def run(cmd):
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 失败: {r.stderr[-300:]}")

    run([ffmpeg, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav_path)])
    # mp3 从原视频直接导出, 保留原音质
    run([ffmpeg, "-y", "-i", str(video), "-vn", "-c:a", "libmp3lame",
         "-q:a", "3", str(mp3_path)])
    dur = 0.0
    try:
        r = subprocess.run([ffmpeg, "-i", str(video)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        for line in (r.stderr or "").splitlines():
            if "Duration:" in line:
                d = line.split("Duration:")[1].split(",")[0].strip()
                hh, mm, ss = d.split(":")
                dur = int(hh) * 3600 + int(mm) * 60 + float(ss)
                break
    except Exception:
        pass
    return dur, video.name


def transcribe(wav_path: Path, model, language: str, hotwords: str,
               progress_cb=None, cpu_threads: int | None = None):
    """转写 wav -> 分段列表; 进度按已识别段的时间戳估算 (0~1)"""
    kw = {"language": None if language == "auto" else "zh",
          "vad_filter": True, "beam_size": 5}
    if cpu_threads:
        kw["cpu_threads"] = cpu_threads
    if hotwords.strip():
        kw["hotwords"] = hotwords.strip()
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
                           "text": text, "speaker": None, "doubt": doubt,
                           "doubt_reason": "语音置信度低" if doubt else ""})
        if progress_cb and total > 0:
            p = min(0.99, seg.end / total)
            if p - last_p >= 0.02 or p >= 0.99:
                last_p = p
                progress_cb(p)
    if progress_cb:
        progress_cb(1.0)
    return result, total
