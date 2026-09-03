/**
 * 全局状态条（T-403）：侧边栏底部的采集/编译/大脑三态聚合 + 索引触发。
 * 数据来自 StatusContext 轮询；采集/编译行可点击跳转对应页面。
 */
import { Link } from 'react-router-dom';
import { useStatus } from './StatusContext';

function Chip(props: { tone: 'ok' | 'warn' | 'err' | 'off'; children: string }) {
  return <span className={`chip chip-${props.tone}`}>{props.children}</span>;
}

export default function StatusRail() {
  const { capture, compile, brain, indexBusy, lastIndexNote, indexBrain } = useStatus();

  // ---- 采集聚合 ----
  let captureTone: 'ok' | 'warn' | 'err' | 'off' = 'off';
  let captureText = '…';
  if (capture.error) {
    captureTone = 'err';
    captureText = '连接失败';
  } else if (capture.data) {
    const { running, sources } = capture.data.manager;
    const errCount = sources.filter((s) => s.status === 'error').length;
    if (running) {
      captureTone = 'ok';
      captureText = errCount > 0 ? `${errCount} 源异常` : `${sources.length} 源`;
    } else {
      captureTone = 'off';
      captureText = '已停止';
    }
  }

  // ---- 编译聚合 ----
  let compileTone: 'ok' | 'warn' | 'err' | 'off' = 'off';
  let compileText = '…';
  if (compile.error) {
    compileTone = 'err';
    compileText = '连接失败';
  } else if (compile.disabled) {
    compileTone = 'off';
    compileText = '未启用';
  } else if (compile.data) {
    const q = compile.data.queue;
    const bits: string[] = [];
    if (q.pending > 0) bits.push(`待 ${q.pending}`);
    if (q.processing > 0) bits.push(`处理中 ${q.processing}`);
    if (q.failed > 0) bits.push(`失败 ${q.failed}`);
    if (compile.data.reviews_open > 0) bits.push(`review ${compile.data.reviews_open}`);
    if (q.paused) {
      compileTone = 'err';
      compileText = bits.length ? `限流暂停 · ${bits.join(' ')}` : '限流暂停';
    } else if (!compile.data.enabled) {
      compileTone = 'off';
      compileText = '停用';
    } else if (!compile.data.llm_ready) {
      compileTone = 'warn';
      compileText = bits.length ? `LLM 未配置 · ${bits.join(' ')}` : 'LLM 未配置';
    } else {
      compileTone = 'ok';
      compileText = bits.length ? bits.join(' ') : '空闲';
    }
  }

  // ---- 大脑聚合 ----
  let brainTone: 'ok' | 'warn' | 'err' | 'off' = 'off';
  let brainText = '…';
  if (brain.error) {
    brainTone = 'err';
    brainText = '连接失败';
  } else if (brain.disabled) {
    brainTone = 'off';
    brainText = '未启用';
  } else if (brain.data) {
    if (brain.data.ready) {
      brainTone = 'ok';
      brainText = '就绪';
    } else {
      brainTone = 'warn';
      brainText = '未就绪';
    }
  }
  const brainReady = brain.data?.ready === true;
  const brainHint = brain.data?.last_error ?? (brain.disabled ? '大脑服务未启用' : null);

  return (
    <aside className="status-rail" aria-label="系统状态">
      <div className="status-rail-title">系统状态</div>
      <Link to="/capture" className="status-row" title="前往采集控制">
        <Chip tone={captureTone}>采集</Chip>
        <span className="status-row-text">{captureText}</span>
      </Link>
      <Link to="/compile" className="status-row" title="前往编译页">
        <Chip tone={compileTone}>编译</Chip>
        <span className="status-row-text">{compileText}</span>
      </Link>
      <div className="status-row" title={brainHint ?? undefined}>
        <Chip tone={brainTone}>大脑</Chip>
        <span className="status-row-text">{brainText}</span>
      </div>
      <div className="status-actions">
        <button
          type="button"
          className="btn btn-sm"
          disabled={!brainReady || indexBusy}
          title={brainReady ? '增量索引：仅写入变更条目' : (brainHint ?? '大脑未就绪')}
          onClick={() => void indexBrain(false)}
        >
          增量索引
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!brainReady || indexBusy}
          title={brainReady ? '全量重建：清空大脑工作目录后重建（较慢）' : (brainHint ?? '大脑未就绪')}
          onClick={() => void indexBrain(true)}
        >
          重建
        </button>
      </div>
      {lastIndexNote && (
        <div className={`status-note${lastIndexNote.ok ? ' ok' : ' err'}`} role="status">
          {indexBusy ? '索引执行中，请稍候…' : lastIndexNote.text}
        </div>
      )}
    </aside>
  );
}
