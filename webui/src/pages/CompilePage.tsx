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

/** /api/compile/queue 单条任务（CompileTask.to_dict） */
interface QueueTask {
  id: string;
  source_path: string;
  status: string; // pending | processing | failed | cancelled
  added_at: number;
  retry_count: number;
  error: string | null;
}

/** 可点击展开的状态键（completed 为会话内存计数器，无明细） */
type QueueFilter = 'pending' | 'processing' | 'failed' | 'completed';

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

  // ---- 队列明细（点击状态数字展开，T-404） ----
  const [expanded, setExpanded] = useState<QueueFilter | null>(null);
  const [tasks, setTasks] = useState<QueueTask[] | null>(null);
  const [tasksErr, setTasksErr] = useState<string | null>(null);

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

  const loadTasks = useCallback(async () => {
    try {
      const r = await api<{ tasks: QueueTask[] }>('/api/compile/queue');
      setTasks(r.tasks);
      setTasksErr(null);
    } catch (e) {
      setTasksErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadReviews();
    const t = setInterval(() => void loadReviews(), REVIEWS_POLL_MS);
    return () => clearInterval(t);
  }, [loadReviews]);

  // 展开期间按 5s 轮询刷新明细；completed 仅为计数器无明细
  useEffect(() => {
    if (!expanded || expanded === 'completed') return;
    void loadTasks();
    const t = setInterval(() => void loadTasks(), REVIEWS_POLL_MS);
    return () => clearInterval(t);
  }, [expanded, loadTasks]);

  async function taskAction(kind: 'retry' | 'cancel' | 'remove', id: string) {
    setBusy(`${kind}:${id}`);
    setTasksErr(null);
    try {
      await api(`/api/compile/${kind}`, { method: 'POST', body: JSON.stringify({ id }) });
      await loadTasks();
      void refresh();
    } catch (e) {
      setTasksErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  // ---- 状态统计（点击展开对应队列明细） ----
  const queueStats: Array<{
    key: QueueFilter;
    label: string;
    en: string;
    num: number;
    err?: boolean;
    hint: string;
  }> = c
    ? [
        {
          key: 'pending',
          label: '待处理',
          en: 'pending',
          num: c.queue.pending,
          hint: '已入队等待编译的素材（扫描到 compiled: false 自动入队）',
        },
        {
          key: 'processing',
          label: '处理中',
          en: 'processing',
          num: c.queue.processing,
          hint: '正在运行编译管线；服务重启后自动回到待处理',
        },
        {
          key: 'failed',
          label: '失败',
          en: 'failed',
          num: c.queue.failed,
          err: c.queue.failed > 0,
          hint: '重试 3 次仍失败，保留在队列直到重试成功或取消',
        },
        {
          key: 'completed',
          label: '完成',
          en: 'completed',
          num: c.queue.completed,
          hint: '本次运行的成功计数；任务成功即出队，无明细',
        },
      ]
    : [];

  /** 当前展开视图下的任务：failed 视图合并展示 cancelled（均需手动处理） */
  const visible = (tasks ?? []).filter((t) =>
    expanded === 'failed'
      ? t.status === 'failed' || t.status === 'cancelled'
      : expanded !== null && t.status === expanded,
  );

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
              {queueStats.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  className={`stat stat-btn${expanded === s.key ? ' open' : ''}`}
                  title={s.hint}
                  aria-pressed={expanded === s.key}
                  onClick={() => setExpanded((p) => (p === s.key ? null : s.key))}
                >
                  <span className={`stat-num${s.err ? ' err' : ''}`}>
                    {s.label} {s.num}
                  </span>
                  <span className="stat-label">{s.en}</span>
                </button>
              ))}
            </div>
            {expanded && (
              <div className="queue-detail">
                {expanded === 'completed' ? (
                  <p className="msg">
                    完成数是本次服务运行期间的成功计数；任务成功后即从队列移除，因此没有明细可查。
                    产出的知识条目可在「知识」页查看。
                  </p>
                ) : (
                  <>
                    <p className="stat-label">队列明细（{visible.length}）</p>
                    {tasksErr && <p className="msg msg-err">队列明细获取失败：{tasksErr}</p>}
                    {tasks === null && !tasksErr ? (
                      <span className="skeleton" style={{ width: '40%' }} />
                    ) : visible.length === 0 ? (
                      <p className="msg">该状态暂无任务</p>
                    ) : (
                      <ul className="queue-list">
                        {visible.map((t) => (
                          <li key={t.id} className="queue-item">
                            <div className="queue-item-head">
                              <span className="path">{t.source_path}</span>
                              <span className="queue-item-meta">
                                {t.status === 'cancelled' && (
                                  <span className="chip chip-off">已取消</span>
                                )}
                                {t.retry_count > 0 && (
                                  <span className="chip chip-warn">已重试 {t.retry_count}</span>
                                )}
                                {t.status === 'failed' || t.status === 'cancelled' ? (
                                  <>
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-sm"
                                      disabled={busy !== null}
                                      onClick={() => void taskAction('retry', t.id)}
                                    >
                                      {busy === `retry:${t.id}` ? '重试中…' : '重试'}
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-sm"
                                      disabled={busy !== null}
                                      title="从队列彻底移除：不再展示也不再重试"
                                      onClick={() => void taskAction('remove', t.id)}
                                    >
                                      {busy === `remove:${t.id}` ? '删除中…' : '删除'}
                                    </button>
                                  </>
                                ) : (
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-sm"
                                    disabled={busy !== null}
                                    onClick={() => void taskAction('cancel', t.id)}
                                  >
                                    {busy === `cancel:${t.id}` ? '取消中…' : '取消'}
                                  </button>
                                )}
                              </span>
                            </div>
                            {t.error && <p className="queue-error">{t.error}</p>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </div>
            )}
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
