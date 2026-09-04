/**
 * 问答页（T-405 / REQ-405 / FR-030）。
 * 带引用的知识库问答：POST /api/brain/query（mode 可切换）+ GET /api/brain/search 独立检索；
 * 引用 file_path → /knowledge?path= 跳转条目原文；对话历史会话内内存保持（不落库）。
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { marked } from 'marked';
import { api } from '../api';
import { useStatus } from '../status/StatusContext';

interface Cite {
  content: string;
  file_path: string;
}

interface Turn {
  id: number;
  question: string;
  answer: string;
  cites: Cite[];
  mode: string;
}

interface Hit {
  content: string;
  file_path: string;
}

const MODES = ['hybrid', 'local', 'global', 'naive', 'mix'] as const;
type Mode = (typeof MODES)[number];

// 会话内内存历史（不落库；路由切换返回不丢，刷新页面即清空）
let memoryTurns: Turn[] = [];
let memoryHits: Hit[] | null = null;
let nextId = 1;

function renderMd(text: string): string {
  return marked.parse(text, { async: false }) as string;
}

export default function AskPage() {
  const { brain } = useStatus();
  const [tab, setTab] = useState<'ask' | 'search'>('ask');

  // 问答流
  const [turns, setTurns] = useState<Turn[]>(memoryTurns);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<Mode>('hybrid');
  const [askBusy, setAskBusy] = useState(false);
  const [askErr, setAskErr] = useState<string | null>(null);

  // 检索
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(10);
  const [hits, setHits] = useState<Hit[] | null>(memoryHits);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);

  const ready = brain.data?.ready === true;

  const ask = useCallback(async () => {
    const q = input.trim();
    if (!q || askBusy) return;
    setAskBusy(true);
    setAskErr(null);
    try {
      const d = await api<{ answer: string; contexts: Cite[]; mode: string }>(
        '/api/brain/query',
        { method: 'POST', body: JSON.stringify({ query: q, mode }) },
      );
      const turn: Turn = {
        id: nextId++,
        question: q,
        answer: d.answer,
        cites: d.contexts ?? [],
        mode,
      };
      memoryTurns = [...memoryTurns, turn];
      setTurns(memoryTurns);
      setInput('');
    } catch (e) {
      setAskErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAskBusy(false);
    }
  }, [input, askBusy, mode]);

  const search = useCallback(async () => {
    const q = query.trim();
    if (!q || searchBusy) return;
    setSearchBusy(true);
    setSearchErr(null);
    try {
      const d = await api<{ hits: Hit[] }>(
        `/api/brain/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
      );
      memoryHits = d.hits ?? [];
      setHits(memoryHits);
    } catch (e) {
      setSearchErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSearchBusy(false);
    }
  }, [query, searchBusy, topK]);

  // 大脑未就绪时清 busy，防卡在旧请求态
  useEffect(() => {
    if (!ready) {
      setAskBusy(false);
      setSearchBusy(false);
    }
  }, [ready]);

  const citeList = (items: Cite[]) => (
    <div className="cite-list">
      {items.map((c, i) => (
        <Link
          key={i}
          className="cite"
          to={`/knowledge?path=${encodeURIComponent(c.file_path)}`}
        >
          <span className="cite-num">[{i + 1}]</span>
          <span className="cite-body">
            <span className="cite-path">{c.file_path}</span>
            <span className="cite-snippet">{c.content.slice(0, 140)}</span>
          </span>
        </Link>
      ))}
    </div>
  );

  const body = () => {
    if (brain.disabled) {
      return (
        <div className="empty">
          <strong>大脑服务未启用</strong>
          在设置页启用大脑（brain.enabled）并配置 embedding 后重启生效
        </div>
      );
    }
    if (brain.error && !brain.data) {
      return <p className="msg msg-err">大脑状态获取失败：{brain.error}</p>;
    }
    if (!brain.data) {
      return (
        <div className="panel">
          <span className="skeleton" style={{ width: '40%' }} />
        </div>
      );
    }
    if (!ready) {
      return (
        <div className="empty">
          <strong>大脑引擎未就绪</strong>
          {brain.data.last_error
            ? `原因：${brain.data.last_error}`
            : '正在启动或缺少 embedding 配置…'}{' '}
          可在侧边栏执行增量/重建索引（需先完成知识编译），就绪后自动可提问。
        </div>
      );
    }
    return tab === 'ask' ? askPanel() : searchPanel();
  };

  const askPanel = () => (
    <>
      <div className="panel">
        <div className="panel-title">
          对话
          <small>引用可点击跳转条目原文 · 历史仅保存在本页会话内</small>
        </div>
        {turns.length === 0 && !askBusy ? (
          <div className="empty">
            <strong>向知识库提问</strong>
            例如：「剪贴板采集有哪些坑？」——回答将附带知识库来源引用
          </div>
        ) : (
          <div className="chat-turns">
            {turns.map((t) => (
              <div className="chat-turn" key={t.id}>
                <div className="chat-q">{t.question}</div>
                <div
                  className="md-body chat-a"
                  dangerouslySetInnerHTML={{ __html: renderMd(t.answer) }}
                />
                {t.cites.length > 0 && citeList(t.cites)}
                <div className="chat-meta">
                  <span className="chip chip-off">mode: {t.mode}</span>
                </div>
              </div>
            ))}
            {askBusy && (
              <div className="chat-turn">
                <div className="chat-q">{input.trim()}</div>
                <div className="chat-a msg">思考中（LightRAG {mode}，需抽取 + 检索 + LLM，约数秒到数十秒）…</div>
              </div>
            )}
          </div>
        )}
        {askErr && <p className="msg msg-err">{askErr}</p>}
      </div>
      <div className="panel ask-input-panel">
        <textarea
          className="textarea"
          placeholder="输入问题，Enter 提问，Shift+Enter 换行"
          value={input}
          rows={2}
          disabled={askBusy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void ask();
            }
          }}
        />
        <div className="toolbar">
          <select
            className="select ask-mode"
            value={mode}
            disabled={askBusy}
            onChange={(e) => setMode(e.target.value as Mode)}
            aria-label="检索模式"
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" disabled={askBusy || !input.trim()} onClick={() => void ask()}>
            提问
          </button>
          {turns.length > 0 && (
            <button
              className="btn btn-ghost"
              disabled={askBusy}
              onClick={() => {
                memoryTurns = [];
                setTurns([]);
              }}
            >
              清空对话
            </button>
          )}
        </div>
      </div>
    </>
  );

  const searchPanel = () => (
    <div className="panel">
      <div className="panel-title">
        语义检索
        <small>直接命中知识库片段，不经 LLM 生成</small>
      </div>
      <div className="toolbar">
        <input
          className="input ask-search-input"
          placeholder="检索词，例如：剪贴板 采集"
          value={query}
          disabled={searchBusy}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void search();
          }}
        />
        <select
          className="select"
          value={topK}
          disabled={searchBusy}
          onChange={(e) => setTopK(Number(e.target.value))}
          aria-label="返回条数"
        >
          {[5, 10, 20].map((n) => (
            <option key={n} value={n}>
              top {n}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" disabled={searchBusy || !query.trim()} onClick={() => void search()}>
          检索
        </button>
      </div>
      {searchErr && <p className="msg msg-err">{searchErr}</p>}
      {searchBusy && <p className="msg">检索中…</p>}
      {hits !== null && !searchBusy && (
        hits.length === 0 ? (
          <p className="msg">无命中——确认知识已索引（侧边栏可执行增量索引）。</p>
        ) : (
          <>
            <p className="msg msg-ok">命中 {hits.length} 条</p>
            {citeList(hits)}
          </>
        )
      )}
    </div>
  );

  return (
    <section className="page page-chat">
      <h1>问答</h1>
      {ready && (
        <div className="tabs" role="tablist">
          <button
            className={`tab${tab === 'ask' ? ' active' : ''}`}
            role="tab"
            aria-selected={tab === 'ask'}
            onClick={() => setTab('ask')}
          >
            问答
          </button>
          <button
            className={`tab${tab === 'search' ? ' active' : ''}`}
            role="tab"
            aria-selected={tab === 'search'}
            onClick={() => setTab('search')}
          >
            检索
          </button>
        </div>
      )}
      {body()}
    </section>
  );
}
