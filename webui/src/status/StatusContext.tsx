/**
 * 全局状态轮询 Context（T-403）。
 * 侧边栏状态条与各页面共享同一份轮询数据，避免重复请求；
 * 5s 轮询对齐旧前端 refresh 节奏。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { api, ApiError } from '../api';

// ---- 类型（对齐后端 manager.get_status / CompileManager.status / BrainEngine.status） ----

export interface SourceInfo {
  name: string;
  status: string; // off | running | error | ...
  error: string | null;
  enabled: boolean;
}

export interface CaptureStatus {
  manager: { running: boolean; sources: SourceInfo[] };
  materials: { count: number };
}

export interface CompileStatus {
  enabled: boolean;
  llm_ready: boolean;
  last_scan: string[];
  last_error: string | null;
  last_warnings: string[];
  queue: {
    pending: number;
    processing: number;
    failed: number;
    completed: number;
    paused: boolean;
  };
  pending: string[];
  reviews_open: number;
}

export interface BrainStatus {
  enabled: boolean;
  ready: boolean;
  lightrag_installed: boolean;
  embedding_configured: boolean;
  embedding_mode: string;
  working_dir: string;
  embedding_dim: number;
  last_error: string | null;
}

export interface IndexResult {
  scanned: number;
  inserted: number;
  skipped: number;
}

/** 单个状态槽：data 最近成功数据；disabled 服务未启用（404）；error 最近错误。 */
export interface StatusSlot<T> {
  data: T | null;
  disabled: boolean;
  error: string | null;
}

const emptySlot = <T,>(): StatusSlot<T> => ({
  data: null,
  disabled: false,
  error: null,
});

interface StatusContextValue {
  capture: StatusSlot<CaptureStatus>;
  compile: StatusSlot<CompileStatus>;
  brain: StatusSlot<BrainStatus>;
  /** 大脑索引执行中（请求未返回） */
  indexBusy: boolean;
  /** 最近一次索引操作的结果描述（成功摘要或错误信息） */
  lastIndexNote: { ok: boolean; text: string } | null;
  refresh: () => Promise<void>;
  indexBrain: (rebuild: boolean) => Promise<IndexResult | null>;
}

const StatusContext = createContext<StatusContextValue | null>(null);

const POLL_MS = 5000;

async function fetchSlot<T>(path: string, slot: StatusSlot<T>): Promise<StatusSlot<T>> {
  try {
    const data = await api<T>(path);
    return { data, disabled: false, error: null };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return { data: null, disabled: true, error: null };
    }
    return { ...slot, data: slot.data, disabled: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export function StatusProvider({ children }: { children: ReactNode }) {
  const [capture, setCapture] = useState<StatusSlot<CaptureStatus>>(emptySlot);
  const [compile, setCompile] = useState<StatusSlot<CompileStatus>>(emptySlot);
  const [brain, setBrain] = useState<StatusSlot<BrainStatus>>(emptySlot);
  const [indexBusy, setIndexBusy] = useState(false);
  const [lastIndexNote, setLastIndexNote] = useState<StatusContextValue['lastIndexNote']>(null);
  // 保持最新槽值供轮询回写（失败时保留上次成功数据）
  const slotsRef = useRef({ capture, compile, brain });
  slotsRef.current = { capture, compile, brain };

  const refresh = useCallback(async () => {
    const [c, k, b] = await Promise.all([
      fetchSlot<CaptureStatus>('/api/status', slotsRef.current.capture),
      fetchSlot<CompileStatus>('/api/compile/status', slotsRef.current.compile),
      fetchSlot<BrainStatus>('/api/brain/status', slotsRef.current.brain),
    ]);
    setCapture(c);
    setCompile(k);
    setBrain(b);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const indexBrain = useCallback(
    async (rebuild: boolean): Promise<IndexResult | null> => {
      setIndexBusy(true);
      try {
        const r = await api<IndexResult>('/api/brain/index', {
          method: 'POST',
          body: JSON.stringify({ rebuild }),
        });
        setLastIndexNote({
          ok: true,
          text: rebuild
            ? `重建完成：扫描 ${r.scanned}，写入 ${r.inserted}`
            : `增量索引完成：扫描 ${r.scanned}，新增 ${r.inserted}，跳过 ${r.skipped}`,
        });
        void refresh();
        return r;
      } catch (e) {
        setLastIndexNote({
          ok: false,
          text: e instanceof Error ? e.message : '索引失败',
        });
        return null;
      } finally {
        setIndexBusy(false);
      }
    },
    [refresh],
  );

  return (
    <StatusContext.Provider
      value={{ capture, compile, brain, indexBusy, lastIndexNote, refresh, indexBrain }}
    >
      {children}
    </StatusContext.Provider>
  );
}

export function useStatus(): StatusContextValue {
  const ctx = useContext(StatusContext);
  if (!ctx) throw new Error('useStatus 必须在 StatusProvider 内使用');
  return ctx;
}
