/**
 * 统一 API 封装：JSON 请求 + 错误归一（FastAPI detail 透出）。
 * 全部页面共用；multipart 等特殊请求可传入自定义 headers 覆盖。
 *
 * [ADR-016 决策 4 · 方案 B sidecar 演进口子] API_BASE 预留 `VITE_API_BASE`
 * 前缀位：方案 B（壳内嵌 dist、Python 后端打包为 sidecar 子进程）时经构建变量
 * 把请求指到后端绝对地址；方案 A（壳加载本机 URL）与浏览器形态不设置该变量
 * （默认空串），请求仍为相对路径，行为与现状一致。
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body?.detail != null) {
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // 非 JSON 响应保持默认错误文本
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}
