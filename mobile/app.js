/* 转写助手 · 手机端逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);
const LS = {
  get: (k, d) => { try { const v = localStorage.getItem("zx-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set: (k, v) => { try { localStorage.setItem("zx-" + k, JSON.stringify(v)); } catch (e) {} },
};

/* ---------- 主题 ---------- */
const THEMES = ["system", "light", "dark"];
const THEME_NAME = { system: "跟随系统", light: "浅色", dark: "深色" };
let theme = LS.get("theme", "system");

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  $("themeBtn").querySelector("use").setAttribute("href",
    t === "dark" ? "#i-moon" : "#i-sun");
}
applyTheme(theme);
$("themeBtn").addEventListener("click", () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  LS.set("theme", theme);
  applyTheme(theme);
  toast("主题：" + THEME_NAME[theme]);
});

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

/* ---------- 配置 ---------- */
const PRESETS = {
  siliconflow: { base: "https://api.siliconflow.cn/v1", model: "FunAudioLLM/SenseVoiceSmall" },
  openai: { base: "https://api.openai.com/v1", model: "whisper-1" },
  custom: { base: "", model: "" },
};

const cfg = {
  provider: LS.get("asrProvider", "siliconflow"),
  base: LS.get("asrBase", PRESETS.siliconflow.base),
  key: LS.get("asrKey", ""),
  model: LS.get("asrModel", PRESETS.siliconflow.model),
  lang: LS.get("asrLang", "zh"),
  llmBase: LS.get("llmBase", "https://api.deepseek.com/v1"),
  llmKey: LS.get("llmKey", ""),
  llmModel: LS.get("llmModel", "deepseek-chat"),
  proof: LS.get("optProof", true),
  summary: LS.get("optSummary", true),
};

function fillSettings() {
  $("asrProvider").value = cfg.provider;
  $("asrBase").value = cfg.base;
  $("asrKey").value = cfg.key;
  $("asrModel").value = cfg.model;
  $("asrLang").value = cfg.lang;
  $("llmBase").value = cfg.llmBase;
  $("llmKey").value = cfg.llmKey;
  $("llmModel").value = cfg.llmModel;
  $("optProof").checked = cfg.proof;
  $("optSummary").checked = cfg.summary;
}

$("asrProvider").addEventListener("change", () => {
  const p = $("asrProvider").value;
  if (PRESETS[p].base) { $("asrBase").value = PRESETS[p].base; $("asrModel").value = PRESETS[p].model; }
});

$("saveSetting").addEventListener("click", () => {
  cfg.provider = $("asrProvider").value;
  cfg.base = $("asrBase").value.trim();
  cfg.key = $("asrKey").value.trim();
  cfg.model = $("asrModel").value.trim();
  cfg.lang = $("asrLang").value;
  cfg.llmBase = $("llmBase").value.trim();
  cfg.llmKey = $("llmKey").value.trim();
  cfg.llmModel = $("llmModel").value.trim();
  cfg.proof = $("optProof").checked;
  cfg.summary = $("optSummary").checked;
  Object.keys(cfg).forEach((k) => LS.set(k, cfg[k]));
  closeSheet();
  toast("设置已保存");
});

/* ---------- 抽屉 ---------- */
function openSheet() {
  fillSettings();
  $("sheet").classList.remove("hidden");
  $("sheetMask").classList.remove("hidden");
}
function closeSheet() {
  $("sheet").classList.add("hidden");
  $("sheetMask").classList.add("hidden");
}
$("settingBtn").addEventListener("click", openSheet);
$("sheetClose").addEventListener("click", closeSheet);
$("sheetMask").addEventListener("click", closeSheet);

/* ---------- 打赏 ---------- */
$("donateBtn").addEventListener("click", () => $("donateModal").classList.remove("hidden"));
$("donateClose").addEventListener("click", () => $("donateModal").classList.add("hidden"));
$("donateModal").addEventListener("click", (e) => {
  if (e.target === $("donateModal")) $("donateModal").classList.add("hidden");
});

/* ---------- 录音 ---------- */
let mediaRecorder = null;
let chunks = [];
let recording = false;
let recStart = 0;
let recTimer = null;
let currentJob = null;   // {xhr, abort}

function pickMime() {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/mpeg"];
  for (const m of cands) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

async function startRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast("当前浏览器不支持录音，请改用「选择音视频」");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime })
                         : new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const type = mediaRecorder.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("mpeg") ? "mp3" : "webm";
      const blob = new Blob(chunks, { type });
      if (blob.size < 2000) { toast("录音太短，已取消"); return; }
      const name = `录音_${stamp()}.${ext}`;
      handleAudio(blob, name);
    };
    mediaRecorder.start(1000);
    recording = true;
    recStart = Date.now();
    $("recBtn").classList.add("recording");
    $("recHint").textContent = "正在录音，点击停止";
    recTimer = setInterval(tickClock, 200);
  } catch (e) {
    toast("无法访问麦克风：" + (e.message || e));
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  recording = false;
  clearInterval(recTimer);
  $("recBtn").classList.remove("recording");
  $("recHint").textContent = "点击开始录音";
}

function tickClock() {
  const s = Math.floor((Date.now() - recStart) / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  $("recTime").textContent = `${mm}:${ss}`;
}

$("recBtn").addEventListener("click", () => {
  if (recording) stopRecording();
  else startRecording();
});

$("fileBtn").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  e.target.value = "";
  if (f) handleAudio(f, f.name);
});

/* ---------- 处理流程 ---------- */
function stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

function showWork(name) {
  $("workPanel").classList.remove("hidden");
  $("workName").textContent = name;
  $("workPct").textContent = "准备中…";
  $("workBar").style.width = "2%";
  $("recBtn").disabled = true;
}

function setWork(pct, label) {
  $("workBar").style.width = Math.round(pct * 100) + "%";
  $("workPct").textContent = label || Math.round(pct * 100) + "%";
}

function hideWork() {
  $("workPanel").classList.add("hidden");
  $("recBtn").disabled = false;
  currentJob = null;
}

async function handleAudio(blob, name) {
  if (!cfg.key) {
    toast("请先点右上角设置，填入识别 API Key");
    openSheet();
    return;
  }
  showWork(name);
  setWork(0.05, "上传中…");
  try {
    const text = await transcribe(blob, name);
    setWork(0.9, "整理文本…");
    showResult(text, name);
    toast("转写完成");
  } catch (e) {
    toast("转写失败：" + (e.message || e));
  } finally {
    hideWork();
  }
}

function transcribe(blob, filename) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    fd.append("model", cfg.model);
    if (cfg.lang && cfg.lang !== "auto") fd.append("language", cfg.lang);

    const xhr = new XMLHttpRequest();
    currentJob = xhr;
    xhr.open("POST", cfg.base.replace(/\/+$/, "") + "/audio/transcriptions");
    xhr.setRequestHeader("Authorization", "Bearer " + cfg.key);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setWork(0.05 + (e.loaded / e.total) * 0.6, "上传 " + Math.round(e.loaded / e.total * 100) + "%");
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          const text = (data.text || data.result || "").trim();
          if (!text) return reject(new Error("识别结果为空"));
          resolve(text);
        } catch (err) {
          reject(new Error("返回格式异常"));
        }
      } else {
        let msg = xhr.responseText.slice(0, 160);
        try { msg = JSON.parse(xhr.responseText).error?.message || msg; } catch (e) {}
        reject(new Error(`${xhr.status} ${msg}`));
      }
    };
    xhr.onerror = () => reject(new Error("网络错误"));
    xhr.onabort = () => reject(new Error("已取消"));
    xhr.timeout = 10 * 60 * 1000;
    xhr.ontimeout = () => reject(new Error("超时"));
    setWork(0.55, "识别中…");
    xhr.send(fd);
  });
}

$("cancelBtn").addEventListener("click", () => {
  if (currentJob) { try { currentJob.abort(); } catch (e) {} }
  hideWork();
  toast("已取消");
});

/* ---------- 结果 ---------- */
let lastResult = { text: "", name: "" };

function showResult(text, name) {
  lastResult = { text, name };
  $("resultPanel").classList.remove("hidden");
  $("resultText").value = text;
  $("resultTitle").textContent = name;
  $("resultMeta").textContent = `${text.length} 字`;
  $("shareBtn").hidden = !(navigator.canShare);
  $("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("resultText").addEventListener("input", () => {
  lastResult.text = $("resultText").value;
  $("resultMeta").textContent = `${lastResult.text.length} 字`;
});

$("closeResult").addEventListener("click", () => $("resultPanel").classList.add("hidden"));

$("copyBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(lastResult.text);
    toast("已复制");
  } catch (e) {
    $("resultText").select();
    document.execCommand("copy");
    toast("已复制");
  }
});

function saveFile() {
  const base = (lastResult.name || "转写结果").replace(/\.[^.]+$/, "");
  const fileName = `${base}_文字记录.txt`;
  // Android 原生壳: WebView 不支持 <a download>, 交给原生写文件
  if (window.ZXAndroid && typeof window.ZXAndroid.saveText === "function") {
    const ok = window.ZXAndroid.saveText(fileName, lastResult.text);
    if (ok) return;
  }
  const blob = new Blob([lastResult.text], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  toast("已保存到「下载/文件」");
}
$("saveBtn").addEventListener("click", saveFile);

$("shareBtn").addEventListener("click", async () => {
  try {
    const base = (lastResult.name || "转写结果").replace(/\.[^.]+$/, "");
    const file = new File([lastResult.text], `${base}_文字记录.txt`, { type: "text/plain" });
    await navigator.share({ files: [file], title: "转写结果" });
  } catch (e) { /* 用户取消 */ }
});

/* ---------- AI 整理 ---------- */
const PROOF_SYS = `你是专业文字校对员。修正错别字与同音字、补全标点、理顺断句，保持原意与顺序，不要增删内容。
直接输出修正后的全文，不要任何解释。`;

const SUM_SYS = `你是内容提炼助手。请基于给定文本输出中文 Markdown 总结，结构：
# 标题
## 一句话摘要
## 核心要点
- 不超过 8 条
## 行动项
- 没有则写"无"
要求：只基于原文，保留关键数字与人名。`;

async function chat(system, user, maxTokens = 3000) {
  if (!cfg.llmKey) throw new Error("未配置 AI Key");
  const base = (cfg.llmBase || "https://api.deepseek.com/v1").replace(/\/+$/, "");
  const res = await fetch(base + "/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + cfg.llmKey,
    },
    body: JSON.stringify({
      model: cfg.llmModel || "deepseek-chat",
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0.3,
      max_tokens: maxTokens,
    }),
  });
  if (!res.ok) {
    let msg = res.status + "";
    try { msg = (await res.json()).error?.message || msg; } catch (e) {}
    throw new Error(msg);
  }
  const data = await res.json();
  return data.choices[0].message.content.trim();
}

$("aiBtn").addEventListener("click", async () => {
  if (!cfg.llmKey) {
    toast("AI 整理需要先配置 Key");
    openSheet();
    return;
  }
  const original = lastResult.text;
  const btn = $("aiBtn");
  btn.disabled = true;
  try {
    let text = original;
    if (cfg.proof) {
      btn.querySelector("span").textContent = "校对中…";
      text = await chat(PROOF_SYS, text, 4000);
      $("resultText").value = text;
      lastResult.text = text;
    }
    if (cfg.summary) {
      btn.querySelector("span").textContent = "总结中…";
      const sum = await chat(SUM_SYS, text, 2000);
      $("resultText").value = text + "\n\n---\n\n" + sum;
      lastResult.text = $("resultText").value;
    }
    $("resultMeta").textContent = `${lastResult.text.length} 字`;
    toast("AI 整理完成");
  } catch (e) {
    toast("AI 整理失败：" + (e.message || e));
  } finally {
    btn.disabled = false;
    btn.querySelector("span").textContent = "AI 整理";
  }
});

/* ---------- PWA ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}
