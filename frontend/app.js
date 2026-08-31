/* 转写助手 前端逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);
const hasPyw = () => !!(window.pywebview && window.pywebview.api);

let state = { tasks: [], settings: null, hardware: null };
let playerTask = null;

/* ---------- 视图切换 ---------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    $("view-" + tab.dataset.view).classList.add("active");
    if (tab.dataset.view === "history") renderHistory();
    if (tab.dataset.view === "settings") fillSettings();
  });
});

/* ---------- 主题 ---------- */
function applyTheme(theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  $("themeBtn").textContent = theme === "dark" ? "☀️" : "🌙";
}
let theme = localStorage.getItem("zhtheme") || "light";
applyTheme(theme);
$("themeBtn").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem("zhtheme", theme);
  applyTheme(theme);
});

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

/* ---------- 添加任务 ---------- */
async function addPaths(paths) {
  if (!paths || !paths.length) return;
  const r = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  const data = await r.json();
  if (data.added && data.added.length) {
    toast(`已加入 ${data.added.length} 个任务`);
    refresh();
  }
}

// 上传严格串行 + 真实进度 + 交互锁定: 避免大文件上传卡死窗口/弹窗循环
let uploading = false;
let picking = false;
let currentXhr = null;
const uploadQueue = [];

function showUpload(fileName, idx, total) {
  $("uploadName").textContent = `正在添加 (${idx}/${total}): ${fileName}`;
  $("uploadBar").style.width = "0%";
  $("uploadBox").classList.remove("hidden");
  $("dropZone").classList.add("busy");
}
function updateUpload(pct) {
  $("uploadBar").style.width = Math.round(pct * 100) + "%";
}
function hideUpload() {
  $("uploadBox").classList.add("hidden");
  $("dropZone").classList.remove("busy");
}

function uploadFile(file, idx, total) {
  return new Promise((resolve) => {
    showUpload(file.name, idx, total);
    const xhr = new XMLHttpRequest();
    currentXhr = xhr;
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) updateUpload(e.loaded / e.total);
    };
    xhr.onload = () => {
      let ok = false;
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.added && data.added.length) ok = true;
      } catch (e) { /* 忽略 */ }
      resolve(ok);
    };
    xhr.onerror = () => resolve(false);
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

async function processUploadQueue() {
  if (uploading) return;
  uploading = true;
  const total = uploadQueue.length;
  try {
    let idx = 0;
    while (uploadQueue.length) {
      const f = uploadQueue.shift();
      idx++;
      const ok = await uploadFile(f, idx, total);
      toast(ok ? `已添加: ${f.name}` : `添加失败: ${f.name}`);
    }
  } finally {
    uploading = false;
    currentXhr = null;
    hideUpload();
    refresh();
  }
}

function enqueueFiles(files) {
  for (const f of files) uploadQueue.push(f);
  if (uploadQueue.length) toast(`已接收 ${uploadQueue.length} 个文件, 正在逐个添加...`);
  processUploadQueue();
}

$("uploadCancel").addEventListener("click", () => {
  if (currentXhr) { try { currentXhr.abort(); } catch (e) {} }
  uploadQueue.length = 0;
  hideUpload();
  toast("已取消添加");
});

// 弹窗时间锁: 对话框关闭后浏览器会在原位置重发 click, 用时间锁拦截
let pickLockUntil = 0;
function pickLocked() {
  return Date.now() < pickLockUntil;
}

$("pickBtn").addEventListener("click", async () => {
  // 上传/弹窗期间锁定, 杜绝对话框循环
  if (uploading || pickLocked()) { toast("正在添加文件, 请稍候..."); return; }
  if (picking) return;
  picking = true;
  try {
    if (hasPyw()) {
      try {
        const paths = await window.pywebview.api.choose_files();
        await addPaths(paths);
        return;
      } catch (e) { /* 落到浏览器上传 */ }
    }
    $("fileInput").click();
  } finally {
    picking = false;
    pickLockUntil = Date.now() + 800;  // 拦截关闭对话框后的重发 click
  }
});
$("browseBtn").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", async (e) => {
  enqueueFiles([...e.target.files]);
  e.target.value = "";
});

const dz = $("dropZone");
dz.addEventListener("click", (e) => {
  if (e.target.closest("button")) return;
  if (uploading || picking || pickLocked()) { toast("正在添加文件, 请稍候..."); return; }
  $("pickBtn").click();
});
["dragover", "dragenter"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
dz.addEventListener("drop", async (e) => {
  const files = [...(e.dataTransfer.files || [])].filter((f) =>
    /\.(mp4|mkv|mov|avi|flv|webm|wmv|m4v|ts|mpg|mpeg|3gp|rmvb|mp3|m4a|aac|wav|flac|ogg|wma)$/i.test(f.name));
  if (!files.length) { toast("没有可处理的视频/音频文件"); return; }
  enqueueFiles(files);
});

/* ---------- 状态轮询 ---------- */
let polling = false;
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const r = await fetch("/api/state");
    state = await r.json();
    renderTasks();
  } catch (e) { /* 服务未就绪 */ }
  polling = false;
}
setInterval(refresh, 1200);
refresh();

/* ---------- 任务卡片 ---------- */
const STATUS_TEXT = { queued: "排队中", running: "处理中", done: "已完成",
  failed: "失败", interrupted: "已中断", canceled: "已取消" };
const ACTIONS = { retry: "重试", cancel: "取消", delete: "删除" };

function renderTasks() {
  const active = state.tasks.filter((t) => t.status !== "done");
  const list = $("taskList");
  if (!active.length) {
    list.innerHTML = '<div class="empty">还没有任务 — 把视频拖进上方区域即可开始</div>';
    return;
  }
  list.innerHTML = active.map(taskCard).join("");
  bindActions();
}

function renderHistory() {
  const done = state.tasks.filter((t) => t.status === "done");
  $("historyCount").textContent = done.length ? `共 ${done.length} 个` : "";
  const list = $("historyList");
  if (!done.length) {
    list.innerHTML = '<div class="empty">还没有完成的任务</div>';
    return;
  }
  list.innerHTML = done.map(taskCard).join("");
  bindActions();
}

function taskCard(t) {
  const stem = t.stem ? `<span class="stem">${escapeHtml(t.stem)}</span>` : "";
  const pct = Math.round((t.progress || 0) * 100);
  const bar = t.status === "done" ? "done" : t.status === "failed" ? "failed" : "";
  const err = t.error ? `<div class="error-text">⚠ ${escapeHtml(t.error)}</div>` : "";
  const out = t.outputs || {};
  const openBtn = out.record
    ? `<button class="btn small" data-act="open" data-id="${t.id}" data-path="${out.record}">📁 打开文件夹</button>` : "";
  const doubtBtns = (t.doubtful || []).slice(0, 6).map((d) =>
    `<button class="doubt-chip" data-act="play" data-id="${t.id}" data-t="${d.t}">` +
    `<span class="t">${d.t}</span>${escapeHtml(d.text)}</button>`).join("");
  const summaryHint = t.status === "done" && !out.summary
    ? '<span class="muted">(未配置API, 未生成总结)</span>' : "";
  const buttons = {
    running: `<button class="btn small" data-act="cancel" data-id="${t.id}">${ACTIONS.cancel}</button>`,
    queued: `<button class="btn small" data-act="cancel" data-id="${t.id}">${ACTIONS.cancel}</button>`,
    failed: `<button class="btn small primary" data-act="retry" data-id="${t.id}">${ACTIONS.retry}</button>` +
            `<button class="btn small danger" data-act="delete" data-id="${t.id}">${ACTIONS.delete}</button>`,
    interrupted: `<button class="btn small primary" data-act="retry" data-id="${t.id}">${ACTIONS.retry}</button>` +
                 `<button class="btn small danger" data-act="delete" data-id="${t.id}">${ACTIONS.delete}</button>`,
    done: `<button class="btn small" data-act="open" data-id="${t.id}">📁 打开文件夹</button>` +
          `<button class="btn small danger" data-act="delete" data-id="${t.id}">删除</button>`,
    canceled: `<button class="btn small" data-act="delete" data-id="${t.id}">删除</button>`,
  }[t.status] || "";

  return `<div class="task-card">
    <div class="task-head">
      <span class="task-video">${escapeHtml(t.video)}${stem}</span>
      <span class="badge ${t.status}">${STATUS_TEXT[t.status] || t.status}</span>
      <span class="muted">${escapeHtml(t.stage || "")} ${t.status === "running" ? pct + "%" : ""}</span>
    </div>
    ${t.status === "running" ? `<div class="progress"><div class="progress-bar ${bar}" style="width:${pct}%"></div></div>` : ""}
    ${err}
    <div class="task-actions">${buttons} ${summaryHint}</div>
    ${doubtBtns ? `<div class="doubts">${doubtBtns}</div>` : ""}
  </div>`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function bindActions() {
  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const { act, id } = btn.dataset;
      if (act === "retry") await fetch(`/api/tasks/${id}/retry`, { method: "POST" });
      if (act === "cancel") await fetch(`/api/tasks/${id}/cancel`, { method: "POST" });
      if (act === "delete") {
        await fetch(`/api/tasks/${id}/delete`, { method: "POST" });
        toast("已删除任务记录");
      }
      if (act === "open") {
        const path = btn.dataset.path || btn.dataset.id;
        if (hasPyw()) { try { await window.pywebview.api.open_folder(path); return; } catch (e) {} }
        await fetch("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
      }
      if (act === "play") openPlayer(id, btn.dataset.t);
      refresh();
    };
  });
}

/* ---------- 存疑试听 ---------- */
function openPlayer(taskId, t) {
  playerTask = taskId;
  $("player").src = `/api/audio/${taskId}`;
  const task = state.tasks.find((x) => x.id === taskId);
  const d = (task?.doubtful || []).find((x) => x.t === t);
  $("doubtDesc").textContent = d ? `[${d.t}] ${d.text}（来源: ${d.source || ""}）` : "";
  $("playerModal").classList.remove("hidden");
  const sec = parseInt(t || "0", 10);
  $("player").addEventListener("loadedmetadata", () => {
    $("player").currentTime = Math.max(0, sec - 1);
    $("player").play();
  }, { once: true });
}
$("playerClose").addEventListener("click", () => {
  $("playerModal").classList.add("hidden");
  $("player").pause();
});

/* ---------- 设置 ---------- */
const PROVIDER_BASES = {
  deepseek: "https://api.deepseek.com/v1",
  openai: "https://api.openai.com/v1",
  custom: "",
};
const PROVIDER_MODELS = { deepseek: "deepseek-chat", openai: "gpt-4o-mini", custom: "" };

function fillSettings() {
  const s = state.settings;
  if (!s) return;
  const api = s.api || {};
  $("setBaseUrl").value = api.base_url || "";
  $("setApiKey").value = api.api_key || "";
  $("setModel").value = api.model || "";
  let provider = "custom";
  for (const [k, v] of Object.entries(PROVIDER_BASES)) {
    if (v && (api.base_url || "").startsWith(v)) provider = k;
  }
  $("setProvider").value = provider;
  $("setTier").value = (s.transcribe || {}).tier || "auto";
  $("setLang").value = (s.transcribe || {}).language || "zh";
  $("setHotwords").value = (s.transcribe || {}).hotwords || "";
  $("setDiarize").checked = !!(s.diarize || {}).enabled;
  $("setHfToken").value = (s.diarize || {}).hf_token || "";
  const hw = state.hardware || {};
  $("hwBox").innerHTML =
    `本机性能: ${hw.cuda ? "✅ 有 NVIDIA 独显(GPU 转写)" : "无独显(CPU 转写)"} · ` +
    `CPU 核数 ${hw.cores || "?"} · 内存 ${hw.ram_gb || "?"} GB<br>` +
    `自动档位建议: ${hw.cuda ? "large-v3 (GPU)" : (hw.cores >= 8 && hw.ram_gb >= 16 ? "large-v3 (CPU)" : "distil-large-v3 或 medium")}`;
}

$("setProvider").addEventListener("change", () => {
  const p = $("setProvider").value;
  if (PROVIDER_BASES[p]) $("setBaseUrl").value = PROVIDER_BASES[p];
  if (PROVIDER_MODELS[p]) $("setModel").value = PROVIDER_MODELS[p];
});

$("saveSettings").addEventListener("click", async () => {
  const s = state.settings || {};
  s.api = {
    provider: $("setProvider").value,
    base_url: $("setBaseUrl").value.trim() || PROVIDER_BASES[$("setProvider").value],
    api_key: $("setApiKey").value.trim(),
    model: $("setModel").value.trim() || PROVIDER_MODELS[$("setProvider").value],
  };
  s.transcribe = {
    tier: $("setTier").value,
    language: $("setLang").value,
    hotwords: $("setHotwords").value,
  };
  s.diarize = { enabled: $("setDiarize").checked, hf_token: $("setHfToken").value.trim() };
  const r = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (r.ok) { toast("设置已保存"); $("settingsHint").textContent = "✓ " + new Date().toLocaleTimeString(); }
  else toast("保存失败");
});
