/**
 * 悬浮控件页（T-504 / REQ-504）：桌面壳透明置顶小窗加载此路由。
 * 仅渲染控件本体（不进 app-shell、不挂 StatusProvider，避免控制台三路
 * 轮询在悬浮窗里重复跑），自带 2s 轮询读取 system_audio 运行态。
 * 拖拽：根容器 data-tauri-drag-region（壳 capability 仅放行 start-dragging，
 * 按钮子元素不带该属性，点击不受影响）。
 */
import { useEffect, useState } from 'react';
import { api } from '../api';

const STATUS_LABEL: Record<string, string> = {
  running: '采集中',
  stopped: '已停止',
  error: '错误',
  off: '已停用',
};

interface StatusPayload {
  manager: {
    running: boolean;
    sources: { name: string; status: string; error?: string | null }[];
  };
}

export default function FloatingPage() {
  const [status, setStatus] = useState<string>('off');
  const [errText, setErrText] = useState('');
  const [busy, setBusy] = useState(false);

  // 悬浮窗透明背景：全局样式给 html/body 深色底，会挡住窗口透明
  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
  }, []);

  // 2s 轮询 system_audio 运行态（不依赖 StatusContext 的三路轮询）
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await api<StatusPayload>('/api/status');
        if (!alive) return;
        const src = s.manager.sources.find((x) => x.name === 'system_audio');
        setStatus(src?.status ?? 'off');
        setErrText(src?.error ?? '');
      } catch {
        // 后端短暂不可达：保留上一状态，下一轮再刷新
      }
    };
    void poll();
    const t = setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  // 开始 = 启用 + 启动；结束 = 停用 + 停止（与采集控制页开关语义一致，
  // stop 由后端收尾最后一段转写，REQ-501）；失败态由下一轮轮询回读呈现
  async function toggle(next: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({ system_audio_enabled: next }),
      });
      await api(next ? '/api/start/system_audio' : '/api/stop/system_audio', {
        method: 'POST',
      });
    } catch {
      // 静默：状态以轮询回读为准
    } finally {
      setBusy(false);
    }
  }

  const running = status === 'running';

  return (
    <div className="floating-root" data-tauri-drag-region>
      <div className="floating-status" data-tauri-drag-region title={errText}>
        <span className={`floating-dot ${status}`} data-tauri-drag-region />
        <span data-tauri-drag-region>
          系统声音 · {STATUS_LABEL[status] ?? status}
        </span>
      </div>
      <div className="floating-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={busy || running}
          onClick={() => void toggle(true)}
        >
          开始
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || !running}
          onClick={() => void toggle(false)}
        >
          结束
        </button>
      </div>
    </div>
  );
}
