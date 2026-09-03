/**
 * 采集控制页（T-408 / REQ-408 / FR-040）。
 * 三区：采集源开关（每源启停 + meeting 引擎就绪）/ 手动导入（文本·文件）/ 网页抓取·飞书导入。
 * 源开关 = enabled 持久化（settings）+ 单源启停（运行态），状态由全局轮询即时反映。
 */
import { useState } from 'react';
import { api } from '../api';
import { useStatus } from '../status/StatusContext';

const SOURCE_META: Record<string, { label: string; sub: string }> = {
  meeting: { label: '会议转写', sub: '热文件夹音频 → VibeASR.cpp 转写' },
  clipboard: { label: '剪贴板', sub: '复制的文本自动入库' },
  feishu: { label: '飞书', sub: '云文档导入（需配置凭据）' },
  file: { label: '文件', sub: '监听目录新增文本文件' },
  web: { label: '网页', sub: 'URL 抓取入库' },
};

const STATUS_LABEL: Record<string, string> = {
  running: '采集中',
  stopped: '已停止',
  error: '错误',
  off: '已停用',
};

interface OpResult {
  ok: boolean;
  text: string;
}

export default function CapturePage() {
  const { capture, refresh } = useStatus();
  const sources = capture.data?.manager.sources ?? [];

  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<OpResult | null>(null);

  // 手动导入表单
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  // 抓取表单
  const [webUrl, setWebUrl] = useState('');
  const [docUrl, setDocUrl] = useState('');

  async function toggleSource(name: string, next: boolean) {
    setBusy(name);
    setNote(null);
    try {
      // ① enabled 持久化（重启后 auto_start 按此生效）
      await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({ [`${name}_enabled`]: next }),
      });
      // ② 运行态单源启停
      await api(next ? `/api/start/${name}` : `/api/stop/${name}`, { method: 'POST' });
      setNote({
        ok: true,
        text: next ? `${SOURCE_META[name]?.label ?? name} 已启动` : `${SOURCE_META[name]?.label ?? name} 已停止`,
      });
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '操作失败' });
      await refresh(); // 回读真实状态，开关与后端保持一致
    } finally {
      setBusy(null);
    }
  }

  async function toggleAll() {
    setBusy('__all__');
    setNote(null);
    try {
      const running = capture.data?.manager.running ?? false;
      await api(running ? '/api/stop' : '/api/start', { method: 'POST' });
      setNote({ ok: true, text: running ? '已停止全部采集源' : '已启动全部采集源' });
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '操作失败' });
    } finally {
      setBusy(null);
    }
  }

  async function importText() {
    setBusy('import');
    setNote(null);
    try {
      const r = await api<{ ok: boolean; path: string }>('/api/import', {
        method: 'POST',
        body: JSON.stringify({ title: title.trim() || '手动导入', text }),
      });
      setNote({ ok: true, text: `已导入：${r.path}` });
      setTitle('');
      setText('');
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '导入失败' });
    } finally {
      setBusy(null);
    }
  }

  async function importFile() {
    if (!file) return;
    setBusy('import');
    setNote(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await api<{ ok: boolean; path: string }>('/api/import/file', {
        method: 'POST',
        headers: {}, // multipart：不设 Content-Type，由 fetch 自动补 boundary
        body: fd,
      });
      setNote({ ok: true, text: `已导入：${r.path}` });
      setFile(null);
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '导入失败' });
    } finally {
      setBusy(null);
    }
  }

  async function webIngest() {
    setBusy('web');
    setNote(null);
    try {
      const r = await api<{ ok: boolean; path: string }>('/api/web/ingest', {
        method: 'POST',
        body: JSON.stringify({ url: webUrl.trim() }),
      });
      setNote({ ok: true, text: `已抓取入库：${r.path}` });
      setWebUrl('');
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '抓取失败' });
    } finally {
      setBusy(null);
    }
  }

  async function feishuImport() {
    setBusy('feishu');
    setNote(null);
    try {
      const r = await api<{ ok: boolean; path: string }>('/api/feishu/doc', {
        method: 'POST',
        body: JSON.stringify({ url: docUrl.trim() }),
      });
      setNote({ ok: true, text: `已导入：${r.path}` });
      setDocUrl('');
      await refresh();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '导入失败' });
    } finally {
      setBusy(null);
    }
  }

  const running = capture.data?.manager.running ?? false;

  return (
    <section className="page">
      <h1>
        采集控制
        <span className="mat-stat" style={{ marginLeft: 12 }}>
          {capture.data ? `素材库 ${capture.data.materials.count} 条` : ''}
        </span>
      </h1>

      {note && <p className={`msg ${note.ok ? 'msg-ok' : 'msg-err'}`}>{note.text}</p>}
      {capture.error && !capture.data && (
        <p className="msg msg-err">采集状态获取失败：{capture.error}</p>
      )}

      {/* ---- 区一：采集源开关 ---- */}
      <div className="panel">
        <h2 className="panel-title">
          采集源
          <small>开关 = 启用并启动 / 停用并停止（持久化到配置）</small>
        </h2>
        <div className="toolbar">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={() => void toggleAll()}
          >
            {running ? '停止全部采集' : '启动全部采集'}
          </button>
        </div>
        <div className="grid2" style={{ marginTop: 12 }}>
          {sources.map((s) => {
            const meta = SOURCE_META[s.name] ?? { label: s.name, sub: '' };
            const meeting = s as typeof s & { engine_ready?: boolean; engine_hint?: string };
            return (
              <div key={s.name} className="src-card">
                <div className="src-head">
                  <span className="src-name">{meta.label}</span>
                  <span
                    className={`chip chip-sm ${
                      s.status === 'running'
                        ? 'chip-ok'
                        : s.status === 'error'
                          ? 'chip-err'
                          : 'chip-off'
                    }`}
                  >
                    {STATUS_LABEL[s.status] ?? s.status}
                  </span>
                  {s.name === 'meeting' && meeting.engine_ready !== undefined && (
                    <span
                      className={`chip chip-sm ${meeting.engine_ready ? 'chip-ok' : 'chip-warn'}`}
                      title={meeting.engine_hint || ''}
                    >
                      {meeting.engine_ready ? '引擎就绪' : '引擎未就绪'}
                    </span>
                  )}
                  <label className="switch src-switch">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      disabled={busy !== null}
                      onChange={(e) => void toggleSource(s.name, e.target.checked)}
                    />
                    <span className="switch-track" />
                  </label>
                </div>
                <span className="src-sub">{meta.sub}</span>
                {s.error && <p className="src-error">{s.error}</p>}
              </div>
            );
          })}
        </div>
      </div>

      {/* ---- 区二：手动导入 ---- */}
      <div className="panel">
        <h2 className="panel-title">手动导入</h2>
        <div className="field">
          <label className="field-label" htmlFor="imp-title">
            标题（可选）
          </label>
          <input
            id="imp-title"
            className="input"
            placeholder="默认：手动导入"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="imp-text">
            文本内容
          </label>
          <textarea
            id="imp-text"
            className="textarea"
            rows={5}
            placeholder="粘贴文本，写入 inbox/manual/"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="toolbar">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null || !text.trim()}
            onClick={() => void importText()}
          >
            导入文本
          </button>
          <input
            type="file"
            className="input"
            style={{ width: 260 }}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null || !file}
            onClick={() => void importFile()}
          >
            上传文件
          </button>
        </div>
      </div>

      {/* ---- 区三：网页抓取 / 飞书导入 ---- */}
      <div className="grid2">
        <div className="panel">
          <h2 className="panel-title">
            网页抓取
            <small>需网页采集源已启用</small>
          </h2>
          <div className="toolbar">
            <input
              className="input"
              style={{ flex: 1 }}
              placeholder="https://example.com/article"
              value={webUrl}
              onChange={(e) => setWebUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && busy === null && webUrl.trim()) void webIngest();
              }}
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy !== null || !webUrl.trim()}
              onClick={() => void webIngest()}
            >
              {busy === 'web' ? '抓取中…' : '抓取入库'}
            </button>
          </div>
        </div>
        <div className="panel">
          <h2 className="panel-title">
            飞书云文档
            <small>粘贴文档链接导入</small>
          </h2>
          <div className="toolbar">
            <input
              className="input"
              style={{ flex: 1 }}
              placeholder="https://xxx.feishu.cn/docs/..."
              value={docUrl}
              onChange={(e) => setDocUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && busy === null && docUrl.trim()) void feishuImport();
              }}
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy !== null || !docUrl.trim()}
              onClick={() => void feishuImport()}
            >
              {busy === 'feishu' ? '导入中…' : '导入'}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
