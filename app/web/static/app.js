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
    $("setMeeting").checked = cfg.sources.meeting;
    $("setClipboard").checked = cfg.sources.clipboard;
    $("setFeishu").checked = cfg.sources.feishu;
    $("setFile").checked = cfg.sources.file;
    $("setWeb").checked = cfg.sources.web;
    $("setFeishuId").placeholder = cfg.feishu_configured ? "已配置（留空不修改）" : "FEISHU_APP_ID";
    $("setCompile").checked = !!cfg.compile.enabled;
    $("setCompileAuto").checked = !!cfg.compile.auto;
    $("setLlBase").value = cfg.compile.llm_base_url || "";
    $("setLlModel").value = cfg.compile.llm_model || "";
    await loadCompile();
    await loadBrain();
  } catch (e) {
    $("overall").textContent = "连接失败";
    $("overall").style.color = "var(--err)";
  }
}

function showTool(ok, summary, detail) {
  setMsg($("toolMsg"), summary, ok);
  const pre = $("toolPre");
  if (detail) { pre.textContent = detail; pre.style.display = "block"; }
  else { pre.style.display = "none"; }
}

async function loadCompile() {
  try {
    const st = await api("/api/compile/status");
    const q = st.queue || {};
    const chips = [
      `<span class="chip">编译: ${st.enabled ? "启用" : "停用"}</span>`,
      `<span class="chip ${st.llm_ready ? "running" : "off"}">LLM: ${st.llm_ready ? "就绪" : "未配置"}</span>`,
    ];
    if (q.paused) chips.push('<span class="chip error">限流暂停</span>');
    chips.push(`<span class="chip">待 ${q.pending || 0} / 处理中 ${q.processing || 0} / 失败 ${q.failed || 0} / 完成 ${q.completed || 0}</span>`);
    chips.push(`<span class="chip">open review: ${st.reviews_open || 0}</span>`);
    $("compileState").innerHTML = chips.join("");
    const info = st.last_error
      ? "最近错误: " + st.last_error
      : (st.last_warnings.length ? "最近警告: " + st.last_warnings.join("；") : "");
    $("compileQueueInfo").textContent = info;
    $("compileQueueInfo").className = "msg" + (st.last_error ? " err" : "");
    $("compilePending").textContent = st.pending.length
      ? "待编译: " + st.pending.join(", ") : "无待编译素材";
  } catch (e) {
    $("compileState").innerHTML = '<span class="chip off">编译服务未启用</span>';
  }
  try {
    const r = await api("/api/compile/reviews");
    $("reviewsBody").innerHTML = r.reviews.length
      ? r.reviews.map((x, i) => `<tr>
          <td>${escapeHtml(x.type)}</td>
          <td>${escapeHtml(x.title)}</td>
          <td>${escapeHtml(x.detail)}</td>
          <td>${escapeHtml(x.source_path)}</td>
          <td>
            <input type="text" id="reviewNote${i}" placeholder="备注" style="width:90px">
            <button class="secondary" data-resolve="${escapeHtml(x.id)}" data-note-id="reviewNote${i}">解决</button>
          </td></tr>`).join("")
      : '<tr><td colspan="5">暂无待处理 review</td></tr>';
  } catch (e) { /* 编译未启用：保留占位 */ }
  try {
    const k = await api("/api/knowledge");
    if (!k.entries.length) { $("kbList").textContent = "知识库为空"; return; }
    $("kbList").innerHTML = k.entries.map((e) =>
      `<button class="secondary" style="margin:2px" data-kb="${escapeHtml(e.path)}">${e.type}/${escapeHtml(e.slug)}</button>`).join("");
  } catch (e) {
    $("kbList").textContent = "知识库不可用";
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

// ---- 大脑（M3）----
function showBrain(ok, summary, detail) {
  setMsg($("brainMsg"), summary, ok);
  const pre = $("brainPre");
  if (detail) { pre.textContent = detail; pre.style.display = "block"; }
  else { pre.style.display = "none"; }
}

async function loadBrain() {
  try {
    const st = await api("/api/brain/status");
    const chips = [
      `<span class="chip">大脑: ${st.enabled ? "启用" : "停用"}</span>`,
      `<span class="chip ${st.ready ? "running" : "off"}">引擎: ${st.ready ? "就绪" : "未就绪"}</span>`,
      `<span class="chip">LightRAG: ${st.lightrag_installed ? "已装" : "缺失"}</span>`,
      `<span class="chip">embedding: ${st.embedding_configured ? "已配置" : "未配置"}</span>`,
      `<span class="chip">dim: ${st.embedding_dim || 0}</span>`,
    ];
    $("brainState").innerHTML = chips.join("");
    $("brainInfo").textContent = st.last_error || "";
    $("brainInfo").className = "msg" + (st.last_error ? " err" : "");
  } catch (e) {
    $("brainState").innerHTML = '<span class="chip off">大脑服务未启用</span>';
  }
}

$("btnBrainIndex").onclick = async () => {
  showBrain(true, "重建索引中（LLM 抽取 + embedding…）");
  try {
    const d = await api("/api/brain/index", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rebuild: true }),
    });
    showBrain(true, `重建完成：扫描 ${d.scanned}，插入 ${d.inserted}`, JSON.stringify(d, null, 2));
    loadBrain();
  } catch (e) { showBrain(false, e.message); }
};

$("btnBrainIndexInc").onclick = async () => {
  showBrain(true, "增量索引中…");
  try {
    const d = await api("/api/brain/index", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rebuild: false }),
    });
    showBrain(true, `增量完成：扫描 ${d.scanned}，插入 ${d.inserted}，跳过 ${d.skipped}`);
    loadBrain();
  } catch (e) { showBrain(false, e.message); }
};

$("btnBrainAsk").onclick = async () => {
  const q = $("brainQuery").value.trim();
  if (!q) return showBrain(false, "请输入问题");
  showBrain(true, "问答中（LightRAG hybrid）…");
  try {
    const d = await api("/api/brain/query", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, mode: "hybrid" }),
    });
    const ctx = (d.contexts || []).map((c) => `[${c.file_path}] ${c.content.slice(0, 120)}`).join("\n");
    showBrain(true, "答案：\n" + d.answer, "来源：\n" + (ctx || "（无）"));
  } catch (e) { showBrain(false, e.message); }
};

$("btnBrainSearch").onclick = async () => {
  const q = $("brainQuery").value.trim();
  if (!q) return showBrain(false, "请输入检索词");
  try {
    const d = await api("/api/brain/search?q=" + encodeURIComponent(q));
    showBrain(true, `检索 ${d.hits.length} 条`, d.hits.length ? JSON.stringify(d.hits, null, 2) : "");
  } catch (e) { showBrain(false, e.message); }
};

$("btnBrainGraph").onclick = async () => {
  try {
    const d = await api("/api/brain/graph");
    showBrain(true, `图谱：${d.nodes.length} 节点 / ${d.edges.length} 边`,
      JSON.stringify(d, null, 2));
  } catch (e) { showBrain(false, e.message); }
};

// ---- 编译（REQ-213）----
$("btnCompileAll").onclick = async () => {
  try {
    const d = await api("/api/compile/trigger", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "all" }),
    });
    setMsg($("compileMsg"), `已入队 ${d.triggered} 条`, true);
    loadCompile();
  } catch (e) { setMsg($("compileMsg"), e.message, false); }
};

$("btnCompilePath").onclick = async () => {
  const p = $("compilePath").value.trim();
  if (!p) return setMsg($("compileMsg"), "请输入 inbox 相对路径", false);
  try {
    const d = await api("/api/compile/trigger", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "path", path: p }),
    });
    setMsg($("compileMsg"), `已入队 ${d.triggered} 条：${p}`, true);
  } catch (e) { setMsg($("compileMsg"), e.message, false); }
};

document.getElementById("reviewsBody").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-resolve]");
  if (!btn) return;
  const note = document.getElementById(btn.dataset.noteId).value.trim();
  try {
    await api("/api/compile/reviews/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: btn.dataset.resolve, note: note || null }),
    });
    loadCompile();
  } catch (e) { alert(e.message); }
});

document.getElementById("kbList").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-kb]");
  if (!btn) return;
  try {
    const d = await api("/api/knowledge?path=" + encodeURIComponent(btn.dataset.kb));
    $("kbContent").textContent = d.content;
    $("kbContent").style.display = "block";
  } catch (e) { alert(e.message); }
});

// ---- 手动工具（REQ-213）----
$("btnLint").onclick = async () => {
  try {
    const d = await api("/api/compile/lint", { method: "POST" });
    showTool(true, `lint：${d.issues.length} 个问题`, d.issues.length ? JSON.stringify(d.issues, null, 2) : "");
  } catch (e) { showTool(false, e.message); }
};

$("btnDedup").onclick = async () => {
  showTool(true, "Dedup 运行中（LLM 批扫…）");
  try {
    const d = await api("/api/compile/dedup", { method: "POST" });
    showTool(true, `dedup：扫描 ${d.scanned} 页，检出 ${d.detected} 组，合并 ${d.merged.length} 组`,
      d.merged.length ? JSON.stringify(d.merged, null, 2) : "");
  } catch (e) { showTool(false, e.message); }
};

$("btnEnrichDry").onclick = async () => {
  showTool(true, "Enrich 预览中（LLM…）");
  try {
    const d = await api("/api/compile/enrich?dry_run=true", { method: "POST" });
    showTool(true, `enrich(dry)：扫描 ${d.scanned} 页，建议 ${d.changes.length} 页变更（未写盘）`,
      d.changes.length ? JSON.stringify(d.changes, null, 2) : "");
  } catch (e) { showTool(false, e.message); }
};

$("btnEnrich").onclick = async () => {
  showTool(true, "Enrich 写入中（LLM…）");
  try {
    const d = await api("/api/compile/enrich", { method: "POST" });
    showTool(true, `enrich：扫描 ${d.scanned} 页，写入 ${d.changes.length} 页`,
      d.changes.length ? JSON.stringify(d.changes, null, 2) : "");
    loadCompile();
  } catch (e) { showTool(false, e.message); }
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
    meeting_enabled: $("setMeeting").checked,
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
  body.compile_enabled = $("setCompile").checked;
  body.compile_auto = $("setCompileAuto").checked;
  const llBase = $("setLlBase").value.trim();
  const llModel = $("setLlModel").value.trim();
  if (llBase) body.llm_base_url = llBase;
  if (llModel) body.llm_model = llModel;
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
