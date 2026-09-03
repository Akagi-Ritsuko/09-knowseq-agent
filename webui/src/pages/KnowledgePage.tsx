/**
 * 知识库浏览页（T-406 / REQ-406）。
 * 展示模式移植自 nashsu/llm_wiki (GPL-3.0) 的 wiki-reader /
 * frontmatter-panel / wiki-page-resolver：
 *   - 条目列表按五类分组，slug 搜索过滤；
 *   - 详情 = frontmatter 面板（title/type/date/tags/related/sources）
 *     + 正文 Markdown 渲染，`[[wikilink]]` 转链接后拦截点击路由跳转，
 *     断链呈现可辨识样式；
 *   - index.md / log.md 走同一条目视图（knowledge 子树内任意文件）。
 * 适配差异：渲染器用项目统一 marked（wiki-reader 为 ReactMarkdown）；
 * 五类 chip 不移植其多彩 icon 方案，保持单一 accent 设计锁定；
 * sources 指向 inbox/ 素材，统一跳素材页。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { marked } from 'marked';
import { api } from '../api';
import {
  CATEGORIES,
  CATEGORY_LABELS,
  filterEntries,
  resolveWikiTarget,
  type KnowledgeEntry,
} from '../lib/knowledge';
import { parseFrontmatter, type FrontmatterValue } from '../lib/frontmatter';
import { safeDecodeUri, transformWikilinks, unwrapWikilink } from '../lib/wikilink';

interface Detail {
  path: string;
  content: string;
}

const FM_KNOWN_KEYS = new Set(['title', 'type', 'created', 'updated', 'tags', 'related', 'sources', 'description']);

export default function KnowledgePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const path = searchParams.get('path') ?? '';

  // 条目索引（列表 + 断链判定共用）
  const [entries, setEntries] = useState<KnowledgeEntry[] | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  // 条目详情
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);

  const loadEntries = useCallback(async () => {
    setListErr(null);
    try {
      const d = await api<{ entries: KnowledgeEntry[] }>('/api/knowledge');
      setEntries(d.entries ?? []);
    } catch (e) {
      setEntries([]);
      setListErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    if (!path) {
      setDetail(null);
      setDetailErr(null);
      return;
    }
    let cancelled = false;
    setDetailBusy(true);
    setDetailErr(null);
    api<Detail>(`/api/knowledge?path=${encodeURIComponent(path)}`)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) {
          setDetail(null);
          setDetailErr(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const html = useMemo(() => {
    if (!detail) return '';
    return marked.parse(transformWikilinks(parseFrontmatter(detail.content).body), {
      async: false,
    }) as string;
  }, [detail]);

  // 渲染后处理：wikilink 断链标样式；外链新窗口打开
  const bodyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.querySelectorAll<HTMLAnchorElement>('a[href^="#"]').forEach((a) => {
      const href = a.getAttribute('href') ?? '';
      const target = safeDecodeUri(href.slice(1));
      const resolved = resolveWikiTarget(target, entries ?? []);
      a.classList.add(resolved ? 'wikilink' : 'wikilink-broken');
      if (!resolved) a.title = `未找到条目：${target}`;
    });
    el.querySelectorAll<HTMLAnchorElement>('a[href^="http"]').forEach((a) => {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    });
  }, [html, entries]);

  if (path) {
    return (
      <section className="page">
        <h1>知识库</h1>
        <div className="kb-crumb">
          <button className="btn btn-ghost" onClick={() => setSearchParams({})}>
            ← 返回列表
          </button>
          <span className="kb-path">{path}</span>
        </div>
        {detailBusy && (
          <div className="panel">
            <span className="skeleton" style={{ width: '35%' }} />
          </div>
        )}
        {detailErr && <p className="msg msg-err">条目读取失败：{detailErr}</p>}
        {detail && !detailBusy && <EntryDetail detail={detail} entries={entries ?? []} />}
      </section>
    );
  }

  // ---- 列表视图 ----
  const shown = entries ? filterEntries(entries, filter) : [];
  const grouped = CATEGORIES.map((cat) => ({
    cat,
    items: shown.filter((e) => e.type === cat),
  }));
  const totalShown = shown.length;

  return (
    <section className="page">
      <h1>知识库</h1>
      <div className="toolbar kb-toolbar">
        <input
          className="input kb-search"
          placeholder="按文件名搜索条目…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="btn btn-ghost" onClick={() => void loadEntries()}>
          刷新
        </button>
        <button className="btn btn-ghost" onClick={() => setSearchParams({ path: 'index.md' })}>
          index.md
        </button>
        <button className="btn btn-ghost" onClick={() => setSearchParams({ path: 'log.md' })}>
          log.md
        </button>
      </div>
      {listErr && <p className="msg msg-err">条目列表读取失败：{listErr}</p>}
      {entries === null ? (
        <div className="panel">
          <span className="skeleton" style={{ width: '60%' }} />
        </div>
      ) : entries.length === 0 ? (
        <div className="empty">
          <strong>知识库暂无条目</strong>
          在「编译」页触发编译，素材将提炼为五类条目落库
        </div>
      ) : totalShown === 0 ? (
        <p className="msg">没有匹配「{filter}」的条目。</p>
      ) : (
        grouped.map(
          ({ cat, items }) =>
            items.length > 0 && (
              <div className="panel" key={cat}>
                <div className="panel-title">
                  {CATEGORY_LABELS[cat]}
                  <small>
                    {cat} · {items.length}
                  </small>
                </div>
                <div className="entry-grid">
                  {items.map((e) => (
                    <Link
                      key={e.path}
                      className="entry"
                      to={`/knowledge?path=${encodeURIComponent(e.path)}`}
                    >
                      <span className="entry-slug">{e.slug}</span>
                    </Link>
                  ))}
                </div>
              </div>
            ),
        )
      )}
    </section>
  );
}

function EntryDetail({ detail, entries }: { detail: Detail; entries: KnowledgeEntry[] }) {
  const { data, body } = useMemo(() => parseFrontmatter(detail.content), [detail]);
  const hasFm = Object.keys(data).length > 0;
  const html = marked.parse(transformWikilinks(body), { async: false }) as string;

  const bodyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.querySelectorAll<HTMLAnchorElement>('a[href^="#"]').forEach((a) => {
      const href = a.getAttribute('href') ?? '';
      const target = safeDecodeUri(href.slice(1));
      const resolved = resolveWikiTarget(target, entries);
      a.classList.add(resolved ? 'wikilink' : 'wikilink-broken');
      if (!resolved) a.title = `未找到条目：${target}`;
    });
    el.querySelectorAll<HTMLAnchorElement>('a[href^="http"]').forEach((a) => {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    });
  }, [html, entries]);

  const onBodyClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const a = (e.target as HTMLElement).closest('a');
    if (!a) return;
    const href = a.getAttribute('href') ?? '';
    if (!href.startsWith('#')) return;
    e.preventDefault();
    const target = safeDecodeUri(href.slice(1));
    const resolved = resolveWikiTarget(target, entries);
    // 跳转由父级 setSearchParams 处理：以 detail 跳转触发路由更新
    if (resolved) window.history.pushState(null, '', `/knowledge?path=${encodeURIComponent(resolved)}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  return (
    <>
      {hasFm && <FrontmatterPanel data={data} entries={entries} />}
      <div
        ref={bodyRef}
        className="panel md-body"
        onClick={onBodyClick}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </>
  );
}

function FrontmatterPanel({
  data,
  entries,
}: {
  data: Record<string, FrontmatterValue>;
  entries: KnowledgeEntry[];
}) {
  const s = (k: string) => (typeof data[k] === 'string' && data[k] ? (data[k] as string) : null);
  const arr = (k: string) => (Array.isArray(data[k]) ? (data[k] as string[]) : []);
  const title = s('title');
  const type = s('type');
  const created = s('created');
  const updated = s('updated');
  const description = s('description');
  const tags = arr('tags');
  const related = arr('related');
  const sources = arr('sources');
  const extras = Object.entries(data).filter(
    ([k, v]) => !FM_KNOWN_KEYS.has(k) && v !== '' && !(Array.isArray(v) && v.length === 0),
  );
  if (!title && !type && !created && tags.length === 0 && related.length === 0 && sources.length === 0 && extras.length === 0) {
    return null;
  }

  return (
    <div className="fm">
      <div className="fm-head">
        {title && <span className="fm-title">{title}</span>}
        {type && <span className="chip chip-sm">{type}</span>}
        {(created || updated) && (
          <span className="fm-date">
            {created}
            {updated && updated !== created ? ` · 更新 ${updated}` : ''}
          </span>
        )}
      </div>
      {description && <div className="fm-desc">{description}</div>}
      {tags.length > 0 && (
        <div className="fm-row">
          <span className="fm-label">标签</span>
          {tags.map((t) => (
            <span className="chip chip-sm chip-off" key={t}>
              {unwrapWikilink(t).label}
            </span>
          ))}
        </div>
      )}
      {related.length > 0 && (
        <div className="fm-row">
          <span className="fm-label">关联</span>
          {related.map((r) => {
            const { slug, label } = unwrapWikilink(r);
            const resolved = resolveWikiTarget(slug, entries);
            return resolved ? (
              <Link
                className="chip chip-sm"
                key={r}
                to={`/knowledge?path=${encodeURIComponent(resolved)}`}
                title={resolved}
              >
                {label}
              </Link>
            ) : (
              <span className="chip chip-sm chip-broken" key={r} title={`未找到条目：${slug}`}>
                {label}
              </span>
            );
          })}
        </div>
      )}
      {sources.length > 0 && (
        <div className="fm-row">
          <span className="fm-label">来源</span>
          {sources.map((src) => {
            const { slug, label } = unwrapWikilink(src);
            return (
              <Link className="chip chip-sm chip-off" key={src} to="/materials" title={slug}>
                {label}
              </Link>
            );
          })}
        </div>
      )}
      {extras.length > 0 && (
        <div className="fm-extras">
          {extras.map(([k, v]) => (
            <div key={k}>
              <span className="k">{k}:</span>
              {Array.isArray(v) ? v.join(', ') : v}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
