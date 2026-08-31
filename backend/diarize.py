# -*- coding: utf-8 -*-
"""说话人区分 (pyannote 3.1)

依赖:
  1. pip install pyannote.audio
  2. HuggingFace 账号接受两个模型授权:
     - pyannote/speaker-diarization-3.1
     - pyannote/segmentation-3.0
  3. 把 HF Access Token 填入软件设置页 "说话人区分"

未配置 Token 时自动跳过, 不影响其他功能。
商用提示: 模型条款要求署名 (CC BY 4.0), 如需完全无限制商用请换 SpeechBrain/NeMo。
"""
import os
import threading
import warnings
from pathlib import Path

# 抑制 torchaudio 弃用提示刷屏(功能不受影响)
warnings.filterwarnings("ignore",
                        message=".*torchaudio.*deprecated.*",
                        category=UserWarning)

_lock = threading.Lock()
_pipeline = None
_pipeline_token = None


def enabled(settings: dict) -> bool:
    s = settings.get("diarize", {})
    return bool(s.get("enabled") and s.get("hf_token", "").strip())


def _ensure_torch_dlls():
    """Windows: torchcodec 的 DLL 依赖 torch/lib, 需提前加入搜索路径"""
    if os.name != "nt":
        return
    try:
        import torch
        lib = Path(torch.__file__).resolve().parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))
        # torch 2.6+ 默认 weights_only=True, pyannote 旧格式权重需放行
        torch.serialization.add_safe_globals([torch.torch_version.TorchVersion])
        # pyannote 官方 checkpoint 含自定义类, 按旧方式加载(权重来自官方, 可信)
        if not getattr(torch.load, "_pyannote_patched", False):
            _orig = torch.load

            def _legacy_load(*a, **kw):
                kw["weights_only"] = False
                return _orig(*a, **kw)

            _legacy_load._pyannote_patched = True
            torch.load = _legacy_load
    except Exception as e:
        print(f"[diarize] torch 初始化异常(不影响转写): {e}")


def _get_pipeline(token: str):
    global _pipeline, _pipeline_token
    with _lock:
        if _pipeline is not None and _pipeline_token == token:
            return _pipeline
        _ensure_torch_dlls()
        # 注意: gated 模型只能从 HuggingFace 官方下载, 需能直连或走系统代理(VPN)。
        # 下载一次后永久缓存(~/.cache/huggingface), 之后离线可用。
        from pyannote.audio import Pipeline
        try:
            p = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", token=token)
        except TypeError:
            # 旧版 pyannote 用 use_auth_token 参数
            p = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", use_auth_token=token)
        try:
            import torch
            if torch.cuda.is_available():
                p.to(torch.device("cuda"))
        except Exception:
            pass
        _pipeline, _pipeline_token = p, token
        return p


def run(audio_path: str, settings: dict, progress_cb=None) -> list:
    """返回 [(start, end, speaker)], speaker 为 'A'/'B'/'C'...
    需要: 设置页已填 HuggingFace Token 且模型授权已接受"""
    token = settings.get("diarize", {}).get("hf_token", "").strip()
    if not token:
        raise RuntimeError("未配置 HuggingFace Token (设置页 → 说话人区分)")
    p = _get_pipeline(token)
    diarization = p(audio_path)
    try:
        dur = diarization.get_duration()
    except AttributeError:
        dur = diarization.get_timeline().duration()  # pyannote 3.x
    spans = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        spans.append((turn.start, turn.end, speaker))
        if progress_cb:
            progress_cb(min(0.99, turn.end / (dur or 1)))
    if progress_cb:
        progress_cb(1.0)
    spans.sort(key=lambda x: x[0])
    return spans
