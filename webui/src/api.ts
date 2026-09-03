/**
 * 统一 API 封装：JSON 请求 + 错误归一（FastAPI detail 透出）。
 * 全部页面共用；multipart 等特殊请求可传入自定义 headers 覆盖。
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
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
