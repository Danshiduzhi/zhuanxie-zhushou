# -*- coding: utf-8 -*-
"""AI 校对与总结 (OpenAI 兼容 API, 默认 DeepSeek)"""
import json
import os
import urllib.request

PROOFREAD_SYSTEM = """你是专业的文字校对员。用户给你一份带时间戳的视频转录稿, 每行格式为 [MM:SS] 文本。
请只做以下工作:
1. 修正错别字、同音字、听错的词(尤其注意同音词, 如"偏负收"常为"偏保守")
2. 补全缺失的标点, 理顺断句
3. 根据用户提供的术语表统一人名/专业术语的写法
4. 若某处语义不通、指代不明或疑似听错, 在该行文本末尾加 [存疑]
5. 保持每行的 [时间戳] 不变, 保持原有的 [存疑] 标记
6. 逐行修改, 严禁合并、删除或新增任何一行, 行数必须与原文完全一致
输出: 修正后的完整转录稿。最后另起一行输出【存疑清单】, 其后每行一条: [时间戳] 疑问描述, 没有则写"无"。"""

SUMMARY_SYSTEM = """你是专业的内容提炼助手。用户会给你一份带时间戳的视频转录稿, 请输出中文 Markdown 总结, 结构固定如下:

# 标题(一行概括主题)
## 一句话摘要
(1-2 句话)
## 核心要点
- 每条要点一行, 不超过 30 字, 按重要性排序, 最多 10 条
## 内容详解
### 主题名称
- 关键信息与数字, 每个主题一节
## 行动项
- 需要跟进的事项; 没有则写"无"
## 存疑问题
- 转录中听不清、指代不明、术语不确定、数字待核实、信息缺失的点; 没有则写"无"

要求: 只基于转录稿内容, 不添加外部信息; 保留关键数字、人名、结论; 存疑问题必须来自转录中确实存在的疑问点。"""

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def call_llm(system: str, user: str, settings: dict, max_tokens: int = 4000) -> str:
    """调用 OpenAI 兼容接口; 失败抛异常"""
    api = settings.get("api", {})
    key = (api.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("未配置 API Key")
    base = (api.get("base_url") or DEFAULT_BASE).rstrip("/")
    model = api.get("model") or DEFAULT_MODEL
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.3, "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def transcript_text(segments: list, total: float) -> str:
    """分段 -> 带时间戳文本"""
    from .naming import ts
    lines = []
    for s in segments:
        t = ts(s["start"], total)
        tag = f" [{s['speaker']}]" if s.get("speaker") else ""
        mark = " [存疑]" if s.get("doubt") else ""
        lines.append(f"[{t}]{tag} {s['text']}{mark}")
    return "\n".join(lines)


def proofread(segments: list, total: float, settings: dict, hotwords: str,
              chunk_chars: int = 4000):
    """AI 校对(分块, 避开单次输出上限): 返回 (修正后全文, 新增存疑清单)"""
    chunks = _split_chunks(segments, chunk_chars)
    extra = f"\n术语表: {hotwords.strip()}" if hotwords.strip() else ""
    parts, doubts = [], []
    for i, chunk in enumerate(chunks):
        src = transcript_text(chunk, total)
        try:
            out = call_llm(PROOFREAD_SYSTEM, f"请校对以下转录稿(第{i+1}/{len(chunks)}部分):{extra}\n\n{src}",
                           settings, max_tokens=8000)
        except Exception:
            parts.append(src)  # 该块校对失败: 退回原文, 不中断
            continue
        body, d = _parse_corrected(out)
        parts.append(body)
        doubts += d
    corrected = "\n".join(parts)
    # 按时间戳与原文对齐: 校对稿缺的行用原文补回, 保证一行不丢
    return merge_corrected(segments, total, corrected), doubts


def merge_corrected(segments: list, total: float, corrected_text: str) -> str:
    """校对稿按时间戳对齐原文: 校对稿优先, 缺失的行回退原文"""
    import re
    from collections import defaultdict, deque
    from .naming import ts as fmt_ts

    by_ts = defaultdict(deque)
    for line in corrected_text.splitlines():
        m = re.match(r"^\[([\d:]+)\]", line.strip())
        if m:
            by_ts[m.group(1)].append(line.strip())
    merged = []
    for seg in segments:
        t = fmt_ts(seg["start"], total)
        q = by_ts.get(t)
        line = q.popleft() if q else None
        if line is None:
            tag = f" [{seg['speaker']}]" if seg.get("speaker") else ""
            mark = " [存疑]" if seg.get("doubt") else ""
            line = f"[{t}]{tag} {seg['text']}{mark}"
        merged.append(line)
    return "\n".join(merged)


def _split_chunks(segments: list, chunk_chars: int) -> list:
    """按字符预算切块, 避免单次 LLM 输出超限被截断"""
    chunks, cur, cur_len = [], [], 0
    for seg in segments:
        ln = len(seg["text"]) + 12  # 时间戳等开销
        if cur and cur_len + ln > chunk_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(seg)
        cur_len += ln
    if cur:
        chunks.append(cur)
    return chunks


def _parse_corrected(out: str) -> tuple[str, list]:
    lines = out.splitlines()
    try:
        idx = next(i for i, l in enumerate(lines) if "存疑清单" in l)
        body, doubt_part = lines[:idx], lines[idx + 1:]
    except StopIteration:
        body, doubt_part = lines, []
    doubts = []
    for l in doubt_part:
        l = l.strip()
        if not l or l == "无":
            continue
        if l.startswith("["):
            l = l.split("]", 1)[1].strip()
        doubts.append(l)
    return "\n".join(body).strip(), doubts


def summarize(text: str, settings: dict) -> str:
    return call_llm(SUMMARY_SYSTEM, f"请总结以下转录稿:\n\n{text}",
                    settings, max_tokens=3000)
