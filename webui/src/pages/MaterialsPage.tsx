/**
 * 素材页（T-408 / REQ-408 / FR-040）。
 * 四区：来源筛选 / 素材列表（待提炼·已提炼徽标 + 标记切换）/ 预览抽屉。
 * 标记回写 inbox 素材 frontmatter 的 compiled 字段，状态即时更新、可反向撤销。
 */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

interface MaterialItem {
  path: string;
  source: string;
  name: string;
  size: number;
  compiled: boolean;
}

interface MaterialDetail {
  path: string;
  source: string;
  captured_at: string;
  compiled: boolean;
  meta: Record<string, unknown>;
  body: string;
}

const SOURCE_TABS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'meeting', label: '会议转写' },
  { key: 'clipboard', label: '剪贴板' },
  { key: 'feishu', label: '飞书' },
  { key: 'file', label: '文件' },
  { key: 'web', label: '网页' },
  { key: 'manual', label: '手动导入' },
];

const SOURCE_LABEL: Record<string, string> = Object.fromEntries(
  SOURCE_TABS.slice(1).map((t) => [t.key, t.label]),
);

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function MaterialsPage() {
  const [items, setItems] = useState<MaterialItem[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState('');
  // 互斥执行标记：标记 / 撤销按钮共享，防并发回写
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [markErr, setMarkErr] = useState<string | null>(null);

  // 预览抽屉
  const [detail, setDetail] = useState<MaterialDetail | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  const load = useCallback(async (source: string) => {
    try {
      const q = source ? `?source=${encodeURIComponent(source)}` : '';
      const r = await api<{ materials: MaterialItem[] }>(`/api/materials${q}`);
      setItems(r.materials);
      setLoadErr(null);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    setItems(null);
    void load(sourceFilter);
  }, [sourceFilter, load]);

  // ESC 关闭抽屉
  useEffect(() => {
    if (!detail) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDetail(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [detail]);

  async function mark(item: MaterialItem, compiled: boolean) {
    setBusyPath(item.path);
    setMarkErr(null);
    try {
      await api('/api/materials/mark', {
        method: 'POST',
        body: JSON.stringify({ path: item.path, compiled }),
      });
      // 状态即时更新（列表 + 抽屉同步）
      setItems((prev) =>
        prev
          ? prev.map((x) => (x.path === item.path ? { ...x, compiled } : x))
          : prev,
      );
      setDetail((d) => (d && d.path === item.path ? { ...d, compiled } : d));
    } catch (e) {
      setMarkErr(e instanceof Error ? e.message : '标记失败');
    } finally {
      setBusyPath(null);
    }
  }

  async function preview(item: MaterialItem) {
    setDetail(null);
    setPreviewErr(null);
    try {
      const d = await api<MaterialDetail>(
        `/api/materials/content?path=${encodeURIComponent(item.path)}`,
      );
      setDetail(d);
    } catch (e) {
      setPreviewErr(e instanceof Error ? e.message : '预览失败');
    }
  }

  const done = items?.filter((x) => x.compiled).length ?? 0;
  const total = items?.length ?? 0;

  return (
    <section className="page">
      <h1>
        素材
        <span className="mat-stat" style={{ marginLeft: 12 }}>
          {items ? `${total} 条 · 已提炼 ${done} · 待提炼 ${total - done}` : ''}
        </span>
      </h1>

      {/* ---- 区一：来源筛选 ---- */}
      <div className="tabs">
        {SOURCE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`tab${sourceFilter === t.key ? ' active' : ''}`}
            onClick={() => setSourceFilter(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ---- 区二：素材列表 ---- */}
      <div className="panel">
        {markErr && <p className="msg msg-err">标记失败：{markErr}</p>}
        {previewErr && <p className="msg msg-err">{previewErr}</p>}
        {loadErr ? (
          <p className="msg msg-err">素材列表获取失败：{loadErr}</p>
        ) : items === null ? (
          <span className="skeleton" style={{ width: '50%' }} />
        ) : items.length === 0 ? (
          <div className="empty">
            <strong>暂无素材</strong>
            开启采集源或手动导入后，素材会出现在这里
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>来源</th>
                <th>文件</th>
                <th>大小</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.path}>
                  <td>
                    <span className="chip chip-sm">{SOURCE_LABEL[x.source] ?? x.source}</span>
                  </td>
                  <td>
                    <span className="path">{x.name}</span>
                  </td>
                  <td className="num">{fmtBytes(x.size)}</td>
                  <td>
                    <span className={`chip chip-sm ${x.compiled ? 'chip-ok' : 'chip-off'}`}>
                      {x.compiled ? '已提炼' : '待提炼'}
                    </span>
                  </td>
                  <td>
                    <div className="review-resolve">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void preview(x)}
                      >
                        预览
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busyPath !== null}
                        onClick={() => void mark(x, !x.compiled)}
                      >
                        {busyPath === x.path
                          ? '处理中…'
                          : x.compiled
                            ? '撤销标记'
                            : '标记已提炼'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---- 预览抽屉 ---- */}
      {detail && (
        <>
          <div className="drawer-backdrop" onClick={() => setDetail(null)} />
          <aside className="drawer" role="dialog" aria-label="素材预览">
            <div className="drawer-head">
              <h2 className="drawer-title">{detail.path}</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDetail(null)}>
                关闭
              </button>
            </div>
            <div className="drawer-body">
              <div className="fm-row">
                <span className="chip chip-sm">{SOURCE_LABEL[detail.source] ?? detail.source}</span>
                <span className={`chip chip-sm ${detail.compiled ? 'chip-ok' : 'chip-off'}`}>
                  {detail.compiled ? '已提炼' : '待提炼'}
                </span>
                {detail.captured_at && <span className="fm-date">{detail.captured_at}</span>}
              </div>
              {Object.keys(detail.meta).length > 0 && (
                <div className="fm-extras" style={{ marginTop: 12 }}>
                  {Object.entries(detail.meta).map(([k, v]) => (
                    <div key={k}>
                      <span className="k">{k}</span>
                      {typeof v === 'string' ? v : JSON.stringify(v)}
                    </div>
                  ))}
                </div>
              )}
              <pre className="pre">{detail.body}</pre>
            </div>
          </aside>
        </>
      )}
    </section>
  );
}
