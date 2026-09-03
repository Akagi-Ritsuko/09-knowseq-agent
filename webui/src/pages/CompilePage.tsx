/**
 * 编译页（T-404 / REQ-404）。
 * 四区：编译状态（消费全局轮询）/ 编译触发 / Review 待处理 / 手动工具。
 * 能力基线对齐旧 static 前端编译面板（app.js 编译区），不回退。
 */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useStatus } from '../status/StatusContext';

interface ReviewItem {
  id: string;
  type: string;
  title: string;
  detail: string;
  source_path: string;
}

interface LintIssue {
  kind: string;
  file: string;
  detail: string;
  suggestion?: string;
  severity?: string;
  broken_target?: string;
}

interface DedupResult {
  scanned: number;
  detected: number;
  merged: unknown[];
}

interface EnrichChange {
  path: string;
  slug: string;
  added_related: string[];
  links: string[];
}

interface EnrichResult {
  scanned: number;
  dry_run: boolean;
  changes: EnrichChange[];
}

interface TriggerResult {
  ok: boolean;
  scope: 'all' | 'path';
  triggered: number;
}

type ToolKey = 'lint' | 'dedup' | 'enrich-dry' | 'enrich-run';

/** Review 列表轮询节奏与全局状态轮询对齐 */
const REVIEWS_POLL_MS = 5000;

export default function CompilePage() {
  const { compile, refresh } = useStatus();
  const c = compile.data;

  // ---- Review 待处理 ----
  const [reviews, setReviews] = useState<ReviewItem[] | null>(null);
  const [reviewsErr, setReviewsErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [resolveNote, setResolveNote] = useState<{ ok: boolean; text: string } | null>(null);

  // ---- 编译触发 ----
  const [pathInput, setPathInput] = useState('');
  const [triggerNote, setTriggerNote] = useState<{ ok: boolean; text: string } | null>(null);

  // ---- 手动工具 ----
  const [toolMsg, setToolMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [lintIssues, setLintIssues] = useState<LintIssue[] | null>(null);
  const [dedupResult, setDedupResult] = useState<DedupResult | null>(null);
  const [enrichResult, setEnrichResult] = useState<EnrichResult | null>(null);

  /** 互斥执行标记：触发 / 工具 / 解决按钮共享，防止并发操作 */
  const [busy, setBusy] = useState<string | null>(null);

  const loadReviews = useCallback(async () => {
    try {
      const r = await api<{ reviews: ReviewItem[] }>('/api/compile/reviews');
      setReviews(r.reviews);
      setReviewsErr(null);
    } catch (e) {
      setReviewsErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadReviews();
    const t = setInterval(() => void loadReviews(), REVIEWS_POLL_MS);
    return () => clearInterval(t);
  }, [loadReviews]);

  async function trigger(scope: 'all' | 'path') {
    setBusy(scope);
    setTriggerNote(null);
    try {
      const body = scope === 'path' ? { scope, path: pathInput.trim() } : { scope };
      const r = await api<TriggerResult>('/api/compile/trigger', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (scope === 'path' && r.triggered === 0) {
        setTriggerNote({ ok: false, text: '未入队：请填写 inbox/ 下的相对路径' });
      } else {
        setTriggerNote({
          ok: true,
          text:
            scope === 'all'
              ? `已入队 ${r.triggered} 条素材`
              : `已入队：${pathInput.trim()}`,
        });
        if (scope === 'path') setPathInput('');
      }
      void refresh();
    } catch (e) {
      setTriggerNote({ ok: false, text: e instanceof Error ? e.message : '触发失败' });
    } finally {
      setBusy(null);
    }
  }

  async function resolveReview(id: string) {
    setBusy(`resolve:${id}`);
    try {
      await api('/api/compile/reviews/resolve', {
        method: 'POST',
        body: JSON.stringify({ id, note: notes[id]?.trim() || null }),
      });
      setResolveNote({ ok: true, text: 'Review 已解决' });
      setNotes((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await loadReviews();
      void refresh();
    } catch (e) {
      setResolveNote({
        ok: false,
        text: e instanceof Error ? e.message : '解决失败',
      });
    } finally {
      setBusy(null);
    }
  }

  async function runTool(key: ToolKey) {
    setBusy(key);
    setToolMsg(null);
    setLintIssues(null);
    setDedupResult(null);
    setEnrichResult(null);
    try {
      if (key === 'lint') {
        const r = await api<{ issues: LintIssue[] }>('/api/compile/lint', { method: 'POST' });
        setLintIssues(r.issues);
        setToolMsg({
          ok: r.issues.length === 0,
          text: r.issues.length === 0 ? 'lint 通过：未发现问题' : `lint 发现 ${r.issues.length} 个问题`,
        });
      } else if (key === 'dedup') {
        const r = await api<DedupResult>('/api/compile/dedup', { method: 'POST' });
        setDedupResult(r);
        setToolMsg({
          ok: true,
          text: `dedup 完成：扫描 ${r.scanned} 页，检出 ${r.detected} 组，合并 ${r.merged.length} 组`,
        });
      } else {
        const dry = key === 'enrich-dry';
        const r = await api<EnrichResult>(`/api/compile/enrich${dry ? '?dry_run=true' : ''}`, {
          method: 'POST',
        });
        setEnrichResult(r);
        setToolMsg({
          ok: true,
          text: dry
            ? `enrich 预览：扫描 ${r.scanned} 页，建议变更 ${r.changes.length} 处（未写盘）`
            : `enrich 完成：扫描 ${r.scanned} 页，写入变更 ${r.changes.length} 处`,
        });
        if (!dry) void refresh();
      }
    } catch (e) {
      setToolMsg({ ok: false, text: e instanceof Error ? e.message : '执行失败' });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="page">
      <h1>编译</h1>

      {/* ---- 区一：编译状态（全局轮询共享数据） ---- */}
      <div className="panel">
        <h2 className="panel-title">
          编译状态
          <small>5s 自动刷新</small>
        </h2>
        {compile.disabled ? (
          <div className="empty">
            <strong>编译服务未启用</strong>
            在 config 中开启 compile.enabled 后可用
          </div>
        ) : compile.error && !c ? (
          <p className="msg msg-err">编译状态获取失败：{compile.error}</p>
        ) : c ? (
          <>
            <div className="toolbar">
              <span className={`chip ${c.enabled ? 'chip-ok' : 'chip-off'}`}>
                {c.enabled ? '启用' : '停用'}
              </span>
              <span className={`chip ${c.llm_ready ? 'chip-ok' : 'chip-warn'}`}>
                {c.llm_ready ? 'LLM 就绪' : 'LLM 未配置'}
              </span>
              {c.queue.paused && <span className="chip chip-err">限流暂停</span>}
            </div>
            <div className="stats">
              <div className="stat">
                <span className="stat-num">待处理 {c.queue.pending}</span>
                <span className="stat-label">pending</span>
              </div>
              <div className="stat">
                <span className="stat-num">处理中 {c.queue.processing}</span>
                <span className="stat-label">processing</span>
              </div>
              <div className="stat">
                <span className={`stat-num${c.queue.failed > 0 ? ' err' : ''}`}>
                  失败 {c.queue.failed}
                </span>
                <span className="stat-label">failed</span>
              </div>
              <div className="stat">
                <span className="stat-num">完成 {c.queue.completed}</span>
                <span className="stat-label">completed</span>
              </div>
            </div>
            {c.last_error && <p className="msg msg-err">上次错误：{c.last_error}</p>}
            {c.last_warnings.length > 0 && (
              <p className="msg msg-warn">警告：{c.last_warnings.join('；')}</p>
            )}
            {c.pending.length > 0 && (
              <>
                <p className="stat-label">待编译清单（{c.pending.length}）</p>
                <ul className="plain-list">
                  {c.pending.map((p) => (
                    <li key={p} className="path">
                      {p}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <span className="skeleton" style={{ width: '60%' }} />
        )}
      </div>

      {/* ---- 区二：编译触发 ---- */}
      <div className="panel">
        <h2 className="panel-title">编译触发</h2>
        <div className="toolbar">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={() => void trigger('all')}
          >
            全部重新入队
          </button>
          <input
            className="input input-mono"
            style={{ width: 320 }}
            placeholder="inbox/素材相对路径，单条入队"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && busy === null) void trigger('path');
            }}
          />
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null}
            onClick={() => void trigger('path')}
          >
            单路径入队
          </button>
        </div>
        {triggerNote && (
          <p className={`msg ${triggerNote.ok ? 'msg-ok' : 'msg-err'}`}>{triggerNote.text}</p>
        )}
      </div>

      {/* ---- 区三：Review 待处理 ---- */}
      <div className="panel">
        <h2 className="panel-title">
          Review 待处理
          <small>{reviews ? `${reviews.length} 条` : ''}</small>
        </h2>
        {reviewsErr && <p className="msg msg-err">Review 列表获取失败：{reviewsErr}</p>}
        {resolveNote && (
          <p className={`msg ${resolveNote.ok ? 'msg-ok' : 'msg-err'}`}>{resolveNote.text}</p>
        )}
        {reviews === null && !reviewsErr ? (
          <span className="skeleton" style={{ width: '40%' }} />
        ) : reviews && reviews.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>类型</th>
                <th>标题</th>
                <th>详情</th>
                <th>来源</th>
                <th>解决</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((r) => (
                <tr key={r.id}>
                  <td>
                    <span className="chip">{r.type}</span>
                  </td>
                  <td>{r.title}</td>
                  <td className="review-detail">{r.detail}</td>
                  <td>
                    <span className="path">{r.source_path}</span>
                  </td>
                  <td>
                    <div className="review-resolve">
                      <input
                        className="input"
                        style={{ width: 140 }}
                        placeholder="备注（可选）"
                        value={notes[r.id] ?? ''}
                        onChange={(e) => setNotes((prev) => ({ ...prev, [r.id]: e.target.value }))}
                      />
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busy !== null}
                        onClick={() => void resolveReview(r.id)}
                      >
                        {busy === `resolve:${r.id}` ? '解决中…' : '解决'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">
            <strong>暂无待处理 Review</strong>
            编译产出进入人工确认环节后会出现在这里
          </div>
        )}
      </div>

      {/* ---- 区四：手动工具 ---- */}
      <div className="panel">
        <h2 className="panel-title">
          手动工具
          <small>lint 纯本地；dedup / enrich 需 LLM</small>
        </h2>
        <div className="toolbar">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null}
            onClick={() => void runTool('lint')}
          >
            结构化 lint
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null}
            onClick={() => void runTool('dedup')}
          >
            重复检测合并
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null}
            onClick={() => void runTool('enrich-dry')}
          >
            wikilink 补全预览
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy !== null}
            onClick={() => void runTool('enrich-run')}
          >
            wikilink 补全写入
          </button>
        </div>
        {busy && !busy.startsWith('resolve:') && (
          <p className="msg">执行中，请稍候…</p>
        )}
        {toolMsg && (
          <p className={`msg ${toolMsg.ok ? 'msg-ok' : 'msg-err'}`}>{toolMsg.text}</p>
        )}
        {lintIssues && lintIssues.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>级别</th>
                <th>类型</th>
                <th>文件</th>
                <th>详情</th>
                <th>建议</th>
              </tr>
            </thead>
            <tbody>
              {lintIssues.map((i, idx) => (
                <tr key={`${i.file}-${i.kind}-${idx}`}>
                  <td>
                    <span className={`chip ${i.severity === 'warning' ? 'chip-warn' : 'chip-off'}`}>
                      {i.severity === 'warning' ? 'warning' : 'info'}
                    </span>
                  </td>
                  <td>
                    <span className="chip">{i.kind}</span>
                  </td>
                  <td>
                    <span className="path">{i.file}</span>
                  </td>
                  <td>{i.detail}</td>
                  <td>{i.suggestion || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {dedupResult && dedupResult.merged.length > 0 && (
          <pre className="pre">{JSON.stringify(dedupResult.merged, null, 2)}</pre>
        )}
        {enrichResult && enrichResult.changes.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>条目</th>
                <th>并入 related</th>
                <th>插入 wikilink</th>
              </tr>
            </thead>
            <tbody>
              {enrichResult.changes.map((ch) => (
                <tr key={ch.path}>
                  <td>
                    <span className="path">{ch.path}</span>
                  </td>
                  <td>{ch.added_related.join('、') || '—'}</td>
                  <td>{ch.links.join('、') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
