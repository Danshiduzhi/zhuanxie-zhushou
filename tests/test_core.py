# -*- coding: utf-8 -*-
"""核心逻辑回归测试（不依赖模型与网络）

运行: python tests/test_core.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config, docgen, engine, naming, proofread  # noqa: E402
from backend.tasks import _is_oom, _norm_created  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def test_naming():
    cases = {
        "20260822_测试录音": "测试录音",
        "录屏 2026-08-31 15-30 产品评审会": "产品评审会",
        "VID_20260831_153012": "未命名",
        "1080p_理财咨询_20260831_x264": "理财咨询",
        "会议录音_最终版_copy": "会议录音 最终版",
    }
    for src, want in cases.items():
        got = naming.clean_label(src)
        check(f"clean_label({src!r})", got == want, f"得到 {got!r}")

    stem, mtime = naming.canonical_stem(Path(__file__).resolve())
    check("canonical_stem 含日期前缀", stem[:10].count("-") == 2, stem)
    check("ts 短格式", naming.ts(75, 300) == "01:15")
    check("ts 长格式", naming.ts(3675, 4000) == "01:01:15")


def test_config():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        cfg = config.default_settings()
        cfg["api"]["api_key"] = "sk-test-123"
        config.save(p, cfg)
        raw = json.loads(p.read_text(encoding="utf-8"))
        check("密钥不明文落盘", raw["api"]["api_key"] != "sk-test-123", raw["api"]["api_key"][:16])
        back = config.load(p)
        check("密钥可解密还原", back["api"]["api_key"] == "sk-test-123", back["api"]["api_key"][:16])
        check("默认包含 device", back["transcribe"].get("device") == "auto")
        check("旧版 diarize 被移除", "diarize" not in back)

        # 历史明文配置兼容
        p.write_text(json.dumps({"api": {"api_key": "plain-key"}}), encoding="utf-8")
        check("兼容历史明文", config.load(p)["api"]["api_key"] == "plain-key")


def test_tasks_helpers():
    check("created 浮点原样", _norm_created(123.5) == 123.5)
    check("created 字符串转时间戳", _norm_created("2026-08-22 09:01:00") > 1_700_000_000)
    check("created 非法值归零", _norm_created(None) == 0.0)
    check("OOM 识别", _is_oom(RuntimeError("CUDA out of memory")) is True)
    check("非 OOM 不误判", _is_oom(RuntimeError("file not found")) is False)


def test_proofread():
    segs = [{"start": 0, "end": 2, "text": "第一行", "doubt": False},
            {"start": 2, "end": 4, "text": "第二行", "doubt": True},
            {"start": 4, "end": 6, "text": "第三行", "doubt": False}]
    corrected = "[00:00] 第一行改\n[00:02] 第二行改 [存疑]"
    merged = proofread.merge_corrected(segs, 10, corrected)
    lines = merged.splitlines()
    check("对齐后行数不变", len(lines) == 3, str(len(lines)))
    check("缺行回退原文", "第三行" in lines[2], lines[2])
    check("存疑标记保留", "[存疑]" in lines[1], lines[1])

    chunks = proofread._split_chunks([{"text": "x" * 100}] * 50, 4000)
    check("分块非空且总量守恒", sum(len(c) for c in chunks) == 50, str(len(chunks)))
    parts = proofread._split_by_chars("a" * 100 + "\n" + "b" * 100, 120)
    check("长文切分", len(parts) >= 2, str(len(parts)))


def test_pick_tier():
    gpu_8 = {"cuda": True, "vram_gb": 8, "cores": 8, "ram_gb": 16}
    gpu_4 = {"cuda": True, "vram_gb": 4, "cores": 8, "ram_gb": 16}
    cpu_strong = {"cuda": False, "vram_gb": 0, "cores": 16, "ram_gb": 32}
    cpu_weak = {"cuda": False, "vram_gb": 0, "cores": 4, "ram_gb": 6}

    m, dev, comp, batch = engine.pick_tier(gpu_8, "auto")
    check("8G 显存用 GPU + large-v3", (m, dev, comp) == ("large-v3", "cuda", "float16"), f"{m}/{dev}/{comp}")
    check("8G 显存批量=8", batch == 8, str(batch))

    m2, dev2, comp2, batch2 = engine.pick_tier(gpu_4, "auto")
    check("4G 显存降精度", comp2 == "int8_float16", comp2)
    check("4G 显存批量=4", batch2 == 4, str(batch2))

    m3, dev3, comp3, batch3 = engine.pick_tier(cpu_strong, "auto")
    check("强 CPU 用 large-v3/int8", (m3, dev3, comp3) == ("large-v3", "cpu", "int8"), f"{m3}/{dev3}/{comp3}")
    check("CPU 不开批量", batch3 == 0, str(batch3))

    _, dev4, _, _ = engine.pick_tier(cpu_weak, "auto")
    check("弱机仍走 CPU", dev4 == "cpu")

    _, dev5, _, batch5 = engine.pick_tier(gpu_8, "auto", "cpu")
    check("强制 CPU 生效", dev5 == "cpu" and batch5 == 0, f"{dev5}/{batch5}")

    _, dev6, _, _ = engine.pick_tier(cpu_strong, "auto", "cuda")
    check("无显卡时强制 GPU 自动回退", dev6 == "cpu", dev6)

    m7, _, _, _ = engine.pick_tier(gpu_8, "medium")
    check("手动档位优先", m7 == "medium", m7)


def test_docgen():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "a.srt"
        segs = [{"start": 0.0, "end": 2.5, "text": "你好"},
                {"start": 2.5, "end": 5.0, "text": "世界"}]
        docgen.build_srt(segs, 5, out)
        content = out.read_text(encoding="utf-8")
        check("srt 序号", content.startswith("1\n"), content[:20])
        check("srt 时间格式", "00:00:00.000 --> 00:00:02.500" in content, content[:60])
        check("srt 文本", "你好" in content and "世界" in content)


def main():
    for fn in (test_naming, test_config, test_tasks_helpers,
               test_proofread, test_pick_tier, test_docgen):
        print(f"\n[{fn.__name__}]")
        fn()
    print(f"\n通过 {len(PASS)} 项, 失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
