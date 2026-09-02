/* KnowSeq Agent 极简控制台前端（T-110 REQ-110） */
"use strict";

const $ = (id) => document.getElementById(id);

function fmtBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

const statusText = {
  running: "运行中", stopped: "已停止", error: "异常",
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function setMsg(el, text, ok) {
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

async function refresh() {
  try {
    const s = await api("/api/status");
    const sources = s.manager.sources;
    $("overall").textContent = s.manager.running ? "● 采集中" : "○ 已停止";
    $("overall").style.color = s.manager.running ? "var(--ok)" : "var(--warn)";
    $("btnToggle").textContent = s.manager.running ? "停止采集" : "开始采集";
    $("sources").innerHTML = sources.map((x) => {
      const cls = x.status;
      const label = `${x.name} · ${statusText[x.status] || x.status}`;
      const extra = x.error ? `（${x.error}）` : "";
      return `<span class="chip ${cls}" title="${escapeHtml(x.error)}">${label}${escapeHtml(extra)}</span>`;
    }).join("");

    const m = await api("/api/materials");
    $("materialsBody").innerHTML = m.materials.length
      ? m.materials.map((x) =>
          `<tr><td>${x.source}</td><td>${escapeHtml(x.name)}</td><td>${fmtBytes(x.size)}</td></tr>`).join("")
      : '<tr><td colspan="3">暂无素材</td></tr>';

    const cfg = await api("/api/settings");
    $("setPort").value = cfg.web_port;
    $("setDirs").value = (cfg.file_dirs || []).join("\n");
    $("setAuto").checked = cfg.auto_start;
    $("setScreen").checked = cfg.sources.screen;
    $("setClipboard").checked = cfg.sources.clipboard;
    $("setFeishu").checked = cfg.sources.feishu;
    $("setFile").checked = cfg.sources.file;
    $("setWeb").checked = cfg.sources.web;
    $("setFeishuId").placeholder = cfg.feishu_configured ? "已配置（留空不修改）" : "FEISHU_APP_ID";
  } catch (e) {
    $("overall").textContent = "连接失败";
    $("overall").style.color = "var(--err)";
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

$("btnRefresh").onclick = refresh;
$("btnToggle").onclick = async () => {
  const s = await api("/api/status");
  await api(s.manager.running ? "/api/stop" : "/api/start", { method: "POST" });
  refresh();
};

$("btnImportText").onclick = async () => {
  const text = $("importText").value.trim();
  if (!text) return setMsg($("importMsg"), "请输入文本", false);
  try {
    const d = await api("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    setMsg($("importMsg"), "已入库: " + d.path, true);
    $("importText").value = "";
    refresh();
  } catch (e) { setMsg($("importMsg"), e.message, false); }
};

$("importFile").onchange = async () => {
  const f = $("importFile").files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const d = await api("/api/import/file", { method: "POST", body: fd });
    setMsg($("importMsg"), "已入库: " + d.path, true);
    refresh();
  } catch (e) { setMsg($("importMsg"), e.message, false); }
};

$("btnWeb").onclick = async () => {
  const url = $("webUrl").value.trim();
  if (!url) return setMsg($("webMsg"), "请输入 URL", false);
  try {
    const d = await api("/api/web/ingest", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    setMsg($("webMsg"), "已入库: " + d.path, true);
    refresh();
  } catch (e) { setMsg($("webMsg"), e.message, false); }
};

$("btnFeishu").onclick = async () => {
  const tok = $("feishuDoc").value.trim();
  if (!tok) return setMsg($("feishuMsg"), "请输入文档 token", false);
  try {
    const d = await api("/api/feishu/doc", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: tok }),
    });
    setMsg($("feishuMsg"), "已入库: " + d.path, true);
    refresh();
  } catch (e) { setMsg($("feishuMsg"), e.message, false); }
};

$("btnSaveSettings").onclick = async () => {
  const dirs = $("setDirs").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const body = {
    web_port: Number($("setPort").value) || 8765,
    auto_start: $("setAuto").checked,
    screen_enabled: $("setScreen").checked,
    clipboard_enabled: $("setClipboard").checked,
    feishu_enabled: $("setFeishu").checked,
    file_enabled: $("setFile").checked,
    web_enabled: $("setWeb").checked,
    file_dirs: dirs,
  };
  const appId = $("setFeishuId").value.trim();
  const secret = $("setFeishuSecret").value.trim();
  if (appId) body.feishu_app_id = appId;
  if (secret) body.feishu_app_secret = secret;
  try {
    await api("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setMsg($("settingsMsg"), "已保存", true);
    $("setFeishuId").value = "";
    $("setFeishuSecret").value = "";
    refresh();
  } catch (e) { setMsg($("settingsMsg"), e.message, false); }
};

refresh();
setInterval(refresh, 5000);
