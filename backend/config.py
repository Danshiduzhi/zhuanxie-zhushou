# -*- coding: utf-8 -*-
"""配置读写: 密钥用 Windows DPAPI 加密落盘, 其余字段明文

DPAPI 用当前 Windows 用户身份加密, 拷走 config.json 到别的电脑解不开,
只能读回明文混淆占位符, 避免"转发文件夹把 Key 一起送出去"。
"""
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

SECRET_FIELDS = (("api", "api_key"),)
ENCRYPT_PREFIX = "dpapi:"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows 数据保护 API; 非 Windows 平台原样返回(上层退化为 base64)"""
    if os.name != "nt":
        raise OSError("DPAPI 仅在 Windows 可用")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _keep = _to_blob(data)
    blob_out = _BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # 参数: pDataIn, szDataDescr, pOptionalEntropy, pvReserved, pPromptStruct, dwFlags, pDataOut
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 调用失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return ENCRYPT_PREFIX + base64.b64encode(
            _dpapi(value.encode("utf-8"), True)).decode("ascii")
    except Exception:
        # 非 Windows 或 DPAPI 异常: 退化为带标记的 base64, 至少不是裸明文
        return "b64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        if value.startswith(ENCRYPT_PREFIX):
            raw = _dpapi(base64.b64decode(value[len(ENCRYPT_PREFIX):]), False)
            return raw.decode("utf-8")
        if value.startswith("b64:"):
            return base64.b64decode(value[4:]).decode("utf-8")
    except Exception:
        return ""   # 换了电脑/换了用户, 解不开就当没有, 让用户重填
    return value       # 兼容历史明文配置


def default_settings() -> dict:
    return {
        "api": {"provider": "deepseek", "base_url": "https://api.deepseek.com/v1",
                "api_key": "", "model": "deepseek-chat"},
        "transcribe": {"tier": "auto", "language": "zh", "hotwords": ""},
        "output": {"keep_source": True,   # 完成后保留源视频与录音
                   "summary": True,       # 生成总结提炼
                   "proofread": True},    # AI 校对
        "ui": {"theme": "system"},
        "work_root": "",
    }


def _merge_defaults(cfg: dict) -> dict:
    base = default_settings()
    for k, v in base.items():
        if k not in cfg or not isinstance(cfg.get(k), dict):
            cfg[k] = v
        else:
            for kk, vv in v.items():
                cfg[k].setdefault(kk, vv)
    cfg.pop("diarize", None)   # 旧版说话人配置已废弃
    return cfg


def load(config_path: Path, legacy_path: Path | None = None) -> dict:
    """读配置: 先读数据目录, 没有再读程序目录(历史版本), 都没有用默认值"""
    raw = {}
    for p in (config_path, legacy_path):
        if p and p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                continue
    cfg = _merge_defaults(raw if isinstance(raw, dict) else {})
    for sec, key in SECRET_FIELDS:
        cfg.setdefault(sec, {})
        cfg[sec][key] = decrypt_secret(cfg[sec].get(key) or "")
    return cfg


def save(path: Path, cfg: dict) -> None:
    """写配置: 密钥加密后落盘, 原子替换避免半截文件"""
    out = json.loads(json.dumps(cfg))   # 深拷贝
    for sec, key in SECRET_FIELDS:
        out.setdefault(sec, {})
        out[sec][key] = encrypt_secret(cfg.get(sec, {}).get(key) or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
        tmp.unlink(missing_ok=True)
