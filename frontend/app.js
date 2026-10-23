/* 转写助手 · 前端逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);
const TOKEN = window.__ZX_TOKEN || "";
const hasPyw = () => !!(window.pywebview && window.pywebview.api);

let state = { tasks: [], settings: null, hardware: null, dirs: {} };
let lastStateJSON = "";
let lastSettingsSig = "";
let currentView = "tasks";

/* ---------- 请求封装 ---------- */
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Token": TOKEN }, opts.headers || {});
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

/* ---------- 主题 ---------- */
const THEMES = ["system", "light", "dark"];
const THEME_ICON = { system: "i-sun", light: "i-sun", dark: "i-moon" };
const THEME_NAME = { system: "跟随系统", light: "浅色", dark: "深色" };

function applyTheme(mode) {
  document.documentElement.dataset.theme = mode;
  const btn = $("themeBtn");
  btn.querySelector("use").setAttribute("href",
    mode === "dark" ? "#i-moon" : mode === "light" ? "#i-sun" : "#i-gear");
  btn.title = "主题：" + THEME_NAME[mode] + "（点击切换）";
}

let themeMode = localStorage.getItem("zx-theme") || "system";
applyTheme(themeMode);

$("themeBtn").addEventListener("click", () => {
  themeMode = THEMES[(THEMES.indexOf(themeMode) + 1) % THEMES.length];
  localStorage.setItem("zx-theme", themeMode);
  applyTheme(themeMode);
  toast("主题：" + THEME_NAME[themeMode]);
});

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
}

/* ---------- 视图切换 ---------- */
document.querySelectorAll(".seg").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    currentView = btn.dataset.view;
    $("view-" + currentView).classList.add("active");
    if (currentView === "settings") {
      fillSettings();
      lastSettingsSig = JSON.stringify(state.settings);
    }
  });
});

/* ---------- 添加文件 ---------- */
const uploadQueue = [];
let uploading = false;
let currentXhr = null;
let picking = false;
let pickLockUntil = 0;

function showUpload(name, idx, total) {
  $("uploadName").textContent = `正在添加 (${idx}/${total})：${name}`;
  $("uploadBar").style.width = "0%";
  $("uploadBox").classList.remove("hidden");
  $("dropZone").classList.add("busy");
}
function hideUpload() {
  $("uploadBox").classList.add("hidden");
  $("dropZone").classList.remove("busy");
}

function uploadOne(file, idx, total) {
  return new Promise((resolve) => {
    showUpload(file.name, idx, total);
    const xhr = new XMLHttpRequest();
    currentXhr = xhr;
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-Token", TOKEN);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        $("uploadBar").style.width = Math.round((e.loaded / e.total) * 100) + "%";
      }
    };
    xhr.onload = () => {
      let ok = false;
      try { ok = !!(JSON.parse(xhr.responseText).added || []).length; } catch (e) {}
      resolve(ok);
    };
    xhr.onerror = () => resolve(false);
    xhr.onabort = () => resolve(false);
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

async function drainQueue() {
  if (uploading) return;
  uploading = true;
  const total = uploadQueue.length;
  let idx = 0;
  try {
    while (uploadQueue.length) {
      const f = uploadQueue.shift();
      idx += 1;
      const ok = await uploadOne(f, idx, total);
      toast(ok ? `已添加：${f.name}` : `添加失败：${f.name}`);
    }
  } finally {
    uploading = false;
    currentXhr = null;
    hideUpload();
    refresh(true);
  }
}

function enqueue(files) {
  const list = [...files];
  if (!list.length) return;
  list.forEach((f) => uploadQueue.push(f));
  toast(`已接收 ${list.length} 个文件，正在逐个添加…`);
  drainQueue();
}

$("uploadCancel").addEventListener("click", () => {
  if (currentXhr) { try { currentXhr.abort(); } catch (e) {} }
  uploadQueue.length = 0;
  hideUpload();
  toast("已取消添加");
});

$("pickBtn").addEventListener("click", async () => {
  if (uploading || picking || Date.now() < pickLockUntil) {
    toast("正在添加文件，请稍候…");
    return;
  }
  picking = true;
  try {
    if (hasPyw()) {
      try {
        const paths = await window.pywebview.api.choose_files();
        if (paths && paths.length) {
          await api("/api/tasks", {
            method: "POST",
            body: JSON.stringify({ paths }),
          });
          toast(`已添加 ${paths.length} 个任务`);
          refresh(true);
        }
        return;
      } catch (e) { /* 回落到浏览器上传 */ }
    }
    $("fileInput").click();
  } finally {
    picking = false;
    pickLockUntil = Date.now() + 700;
  }
});

$("fileInput").addEventListener("change", (e) => {
  enqueue(e.target.files);
  e.target.value = "";
});

const dz = $("dropZone");
["dragover", "dragenter"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.add("dragover");
  }));
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.remove("dragover");
  }));
dz.addEventListener("drop", (e) => {
  const files = [...(e.dataTransfer.files || [])].filter((f) =>
    /\.(mp4|mkv|mov|avi|flv|webm|wmv|m4v|ts|mpg|mpeg|3gp|rmvb|mp3|m4a|aac|wav|flac|ogg|wma|amr)$/i
      .test(f.name));
  if (!files.length) { toast("没有可处理的音视频文件"); return; }
  enqueue(files);
});

/* ---------- 状态轮询 ---------- */
let polling = false;
async function refresh(force = false) {
  if (polling) return;
  polling = true;
  try {
    const data = await api("/api/state");
    const sig = JSON.stringify([data.tasks, data.settings, data.hardware, data.dirs]);
    if (!force && sig === lastStateJSON) return;
    lastStateJSON = sig;
    state = data;
    renderAll();
  } catch (e) {
    if (e.message === "unauthorized") {
      toast("连接已失效，请重新打开软件");
    }
  } finally {
    polling = false;
  }
}
setInterval(refresh, 1200);
refresh(true);

/* ---------- 渲染 ---------- */
const STATUS_TEXT = {
  queued: "排队中", running: "处理中", done: "已完成",
  failed: "失败", interrupted: "已中断", canceled: "已取消",
};
const STATUS_ICON = {
  queued: "i-clock", running: "i-refresh", done: "i-check",
  failed: "i-alert", interrupted: "i-alert", canceled: "i-x",
};

function fmtDuration(sec) {
  if (!sec) return "";
  const m = Math.round(sec / 60);
  if (m < 60) return `${m} 分钟`;
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

/** 从 stem（2026-08-31_15-30_理财咨询）拆出时间与内容标签 */
function splitStem(stem, fallbackName) {
  if (!stem) return { time: "", label: fallbackName || "" };
  const parts = stem.split("_");
  if (parts.length >= 3) {
    const date = parts[0];
    const time = parts[1].replace("-", ":");
    const label = parts.slice(2).join(" ");
    return { time: `${date.slice(5)} ${time}`, label };
  }
  return { time: "", label: stem };
}

function taskCard(t) {
  const { time, label } = splitStem(t.stem, t.video);
  const pct = Math.round((t.progress || 0) * 100);
  const status = t.status || "queued";
  const icon = STATUS_ICON[status] || "i-clock";
  const dur = fmtDuration((t.meta || {}).duration);
  const outs = t.outputs || {};

  const chips = [];
  if (time) chips.push(`<span class="chip time">${escapeHtml(time)}</span>`);
  if (dur) chips.push(`<span class="chip">${dur}</span>`);

  const subParts = [];
  if (status === "running") subParts.push(`${t.stage || ""} ${pct}%`);
  else if (status === "done") subParts.push((t.meta || {}).model || "已完成");
  else if (status === "failed") subParts.push("处理失败");
  else if (status === "canceled") subParts.push("已取消");
  else if (status === "interrupted") subParts.push("程序中断，可重试");
  else subParts.push("排队中");
  if (t.meta && t.meta.video && status !== "done") subParts.push(t.meta.video);

  const actions = [];
  if (status === "done") {
    if (outs.record) {
      actions.push(btn("open-doc", t.id, outs.record, "i-file", "打开记录"));
    }
    actions.push(btn("open-folder", t.id, outs.folder || outs.record, "i-folder", "位置"));
    actions.push(btn("delete", t.id, "", "i-trash", "", "danger"));
  } else if (status === "running") {
    actions.push(btn("cancel", t.id, "", "i-x", "取消"));
  } else if (status === "queued") {
    actions.push(btn("cancel", t.id, "", "i-x", "取消"));
  } else {
    actions.push(btn("retry", t.id, "", "i-refresh", "重试"));
    actions.push(btn("delete", t.id, "", "i-trash", "", "danger"));
  }

  const doubts = (t.doubtful || []).slice(0, 5).map((d) =>
    `<button class="doubt-chip" data-act="play" data-id="${t.id}" data-t="${escapeHtml(d.t)}">` +
    `<span class="t">${escapeHtml(d.t)}</span>${escapeHtml(d.text)}</button>`).join("");

  return `<div class="task">
    <div class="task-top">
      <div class="status-dot ${status}"><svg><use href="#${icon}"/></svg></div>
      <div class="task-main">
        <div class="task-title">
          <span class="label">${escapeHtml(label)}</span>${chips.join("")}
        </div>
        <div class="task-sub">${escapeHtml(subParts.join(" · "))}</div>
      </div>
      <div class="task-actions">${actions.join("")}</div>
    </div>
    ${status === "running" ? `<div class="task-progress"><div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div></div>` : ""}
    ${t.error && status !== "done" ? `<div class="task-error">${escapeHtml(t.error)}</div>` : ""}
    ${doubts ? `<div class="doubts">${doubts}</div>` : ""}
  </div>`;
}

function btn(act, id, path, icon, text, extra = "") {
  return `<button class="btn tiny ${extra}" data-act="${act}" data-id="${id}" data-path="${escapeHtml(path || "")}" title="${escapeHtml(text || "")}">` +
    `<svg><use href="#${icon}"/></svg>${text ? `<span>${text}</span>` : ""}</button>`;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function editingSettings() {
  const el = document.activeElement;
  if (!el || !el.closest) return false;
  const tag = el.tagName;
  return !!el.closest("#view-settings") &&
    (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT");
}

function renderAll() {
  const tasks = (state.tasks || []).slice();
  const active = tasks.filter((t) => t.status !== "done");
  const done = tasks.filter((t) => t.status === "done")
    .sort((a, b) => (a.created || 0) - (b.created || 0));   // 时间升序：早的在上

  $("activeCount").textContent = active.length ? `${active.length} 个` : "";
  $("taskList").innerHTML = active.length
    ? active.map(taskCard).join("")
    : '<div class="empty">还没有进行中的任务</div>';

  $("historyCount").textContent = done.length ? `共 ${done.length} 个` : "";
  $("historyList").innerHTML = done.length
    ? done.map(taskCard).join("")
    : '<div class="empty">还没有完成的任务</div>';

  // 设置页只在设置真正变化时回填, 且用户正在输入时不打断
  if (currentView === "settings" && !editingSettings()) {
    const sig = JSON.stringify(state.settings);
    if (sig !== lastSettingsSig) {
      fillSettings();
      lastSettingsSig = sig;
    }
  }
  bindActions();
}

/* ---------- 通用操作 ---------- */
function bindActions() {
  document.querySelectorAll("[data-act]").forEach((el) => {
    el.onclick = async (e) => {
      e.stopPropagation();
      const { act, id, path, t } = el.dataset;
      try {
        if (act === "retry") await api(`/api/tasks/${id}/retry`, { method: "POST" });
        else if (act === "cancel") await api(`/api/tasks/${id}/cancel`, { method: "POST" });
        else if (act === "delete") {
          await api(`/api/tasks/${id}/delete`, { method: "POST" });
          toast("已删除任务记录");
        } else if (act === "open-folder") await openPath(path);
        else if (act === "open-doc") await openFile(path);
        else if (act === "play") openPlayer(id, t);
      } catch (err) {
        toast("操作失败：" + err.message);
      }
      refresh(true);
    };
  });
}

async function openPath(path) {
  if (!path) { toast("没有可打开的位置"); return; }
  if (hasPyw()) {
    try { await window.pywebview.api.show_in_folder(path); return; } catch (e) {}
  }
  await api("/api/open", { method: "POST", body: JSON.stringify({ path }) });
}

async function openFile(path) {
  if (!path) return;
  if (hasPyw()) {
    try { await window.pywebview.api.open_file(path); return; } catch (e) {}
  }
  await api("/api/open-file", { method: "POST", body: JSON.stringify({ path }) });
}

$("openDocsBtn").addEventListener("click", () => openPath(state.dirs && state.dirs.docs));
$("openRootBtn").addEventListener("click", () => openPath(state.dirs && state.dirs.root));

/* ---------- 试听 ---------- */
function openPlayer(taskId, t) {
  const audio = $("player");
  audio.src = `/api/audio/${taskId}?token=${encodeURIComponent(TOKEN)}`;
  const task = (state.tasks || []).find((x) => x.id === taskId);
  const d = ((task || {}).doubtful || []).find((x) => x.t === t);
  $("doubtDesc").textContent = d
    ? `[${d.t}] ${d.text}（${d.source || ""}）` : "";
  $("playerModal").classList.remove("hidden");
  const sec = parseInt((t || "0").split(":").pop(), 10) || 0;
  audio.addEventListener("loadedmetadata", () => {
    audio.currentTime = Math.max(0, sec - 1);
    audio.play().catch(() => {});
  }, { once: true });
}

$("playerClose").addEventListener("click", () => {
  $("playerModal").classList.add("hidden");
  $("player").pause();
});

/* ---------- 打赏 ---------- */
$("donateBtn").addEventListener("click", () => {
  $("donateModal").classList.remove("hidden");
});
$("donateClose").addEventListener("click", () => {
  $("donateModal").classList.add("hidden");
});

/* ---------- 日志 ---------- */
$("logBtn").addEventListener("click", async () => {
  $("logModal").classList.remove("hidden");
  $("logText").textContent = "加载中…";
  try {
    const r = await api("/api/log");
    $("logText").textContent = r.log || "（暂无日志）";
    $("logText").scrollTop = $("logText").scrollHeight;
  } catch (e) {
    $("logText").textContent = "读取失败：" + e.message;
  }
});
$("logClose").addEventListener("click", () => $("logModal").classList.add("hidden"));
document.querySelectorAll(".modal").forEach((m) => {
  m.addEventListener("click", (e) => {
    if (e.target === m) m.classList.add("hidden");
  });
});

/* ---------- 设置 ---------- */
const PROVIDER_BASES = {
  deepseek: "https://api.deepseek.com/v1",
  openai: "https://api.openai.com/v1",
  custom: "",
};
const PROVIDER_MODELS = {
  deepseek: "deepseek-chat",
  openai: "gpt-4o-mini",
  custom: "",
};

function fillSettings() {
  const s = state.settings;
  if (!s) return;
  const apiSec = s.api || {};
  $("setBaseUrl").value = apiSec.base_url || "";
  $("setApiKey").value = apiSec.api_key || "";
  $("setModel").value = apiSec.model || "";

  let provider = "custom";
  for (const [k, v] of Object.entries(PROVIDER_BASES)) {
    if (v && (apiSec.base_url || "").startsWith(v)) provider = k;
  }
  $("setProvider").value = provider;

  const tr = s.transcribe || {};
  $("setTier").value = tr.tier || "auto";
  $("setLang").value = tr.language || "zh";
  $("setHotwords").value = tr.hotwords || "";

  const out = s.output || {};
  $("setKeepSource").checked = out.keep_source !== false;
  $("setSummary").checked = out.summary !== false;
  $("setProofread").checked = out.proofread !== false;

  $("setWorkRoot").value = s.work_root || "";
  $("rootPath").textContent = (state.dirs && state.dirs.root) || "—";
  $("rootPath").title = (state.dirs && state.dirs.root) || "";

  const hw = state.hardware || {};
  const tierHint = hw.cuda
    ? "large-v3（GPU 加速）"
    : (hw.cores >= 8 && hw.ram_gb >= 16)
      ? "large-v3（CPU）"
      : (hw.ram_gb >= 8 ? "distil-large-v3" : "medium 或 small");
  $("hwBox").innerHTML =
    `<b>本机</b>：${hw.cuda ? "NVIDIA 显卡（GPU 转写）" : "无独显（CPU 转写）"}` +
    ` · ${hw.cores || "?"} 核 · ${hw.ram_gb || "?"} GB 内存<br>` +
    `<b>建议档位</b>：${tierHint}` +
    (hw.gpu_name ? ` · ${escapeHtml(hw.gpu_name)}` : "");
}

$("setProvider").addEventListener("change", () => {
  const p = $("setProvider").value;
  if (PROVIDER_BASES[p]) $("setBaseUrl").value = PROVIDER_BASES[p];
  if (PROVIDER_MODELS[p]) $("setModel").value = PROVIDER_MODELS[p];
});

$("saveSettings").addEventListener("click", async () => {
  const s = JSON.parse(JSON.stringify(state.settings || {}));
  const provider = $("setProvider").value;
  s.api = {
    provider,
    base_url: $("setBaseUrl").value.trim() || PROVIDER_BASES[provider],
    api_key: $("setApiKey").value.trim(),
    model: $("setModel").value.trim() || PROVIDER_MODELS[provider],
  };
  s.transcribe = {
    tier: $("setTier").value,
    language: $("setLang").value,
    hotwords: $("setHotwords").value,
  };
  s.output = {
    keep_source: $("setKeepSource").checked,
    summary: $("setSummary").checked,
    proofread: $("setProofread").checked,
  };
  s.work_root = $("setWorkRoot").value.trim();
  try {
    const r = await api("/api/settings", { method: "POST", body: JSON.stringify(s) });
    toast("设置已保存");
    $("settingsHint").textContent = "已保存 " + new Date().toLocaleTimeString();
    if (r.root && state.dirs) state.dirs.root = r.root;
    refresh(true);
  } catch (e) {
    toast("保存失败：" + e.message);
  }
});
