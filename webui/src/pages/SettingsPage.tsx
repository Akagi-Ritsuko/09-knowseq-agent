/**
 * 设置页（T-410 / REQ-410 / FR-042）。
 * 分组表单对齐 config 结构：LLM API / Embedding / 大脑 / 编译 / 监听与采集 / Web。
 * 敏感项（LLM_API_KEY / 飞书凭据）只写不回读，输入框仅占位提示；
 * 保存后部分项（Web 端口、编译/大脑 LLM、Embedding）重启服务生效。
 */
import { useEffect, useState } from 'react';
import { api } from '../api';

interface Settings {
  web_port: number;
  auto_start: boolean;
  sources: Record<string, boolean>;
  file_dirs: string[];
  drop_dir: string;
  feishu_configured: boolean;
  compile: {
    enabled: boolean;
    auto: boolean;
    llm_base_url: string;
    llm_model: string;
    llm_key_configured: boolean;
  };
  brain: {
    enabled: boolean;
    embedding_base_url: string;
    embedding_model: string;
    llm_base_url: string;
    llm_model: string;
  };
  llm_key_configured: boolean;
  autostart: boolean;
  autostart_installed: boolean;
  context_menu_installed: boolean;
}

interface FormState {
  webPort: number | '';
  autoStart: boolean;
  sources: Record<string, boolean>;
  fileDirsText: string;
  compileEnabled: boolean;
  compileAuto: boolean;
  llmBaseUrl: string;
  llmModel: string;
  brainEnabled: boolean;
  brainEmbeddingBaseUrl: string;
  brainEmbeddingModel: string;
  brainLlmBaseUrl: string;
  brainLlmModel: string;
  feishuAppId: string;
  feishuAppSecret: string;
  autostart: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  meeting: '会议转写',
  system_audio: '系统声音',
  clipboard: '剪贴板',
  feishu: '飞书',
  file: '文件',
  web: '网页',
};

function applySettings(s: Settings): FormState {
  return {
    webPort: s.web_port,
    autoStart: s.auto_start,
    sources: { ...s.sources },
    fileDirsText: (s.file_dirs ?? []).join('\n'),
    compileEnabled: s.compile.enabled,
    compileAuto: s.compile.auto,
    llmBaseUrl: s.compile.llm_base_url,
    llmModel: s.compile.llm_model,
    brainEnabled: s.brain.enabled,
    brainEmbeddingBaseUrl: s.brain.embedding_base_url,
    brainEmbeddingModel: s.brain.embedding_model,
    brainLlmBaseUrl: s.brain.llm_base_url,
    brainLlmModel: s.brain.llm_model,
    feishuAppId: '',
    feishuAppSecret: '',
    autostart: s.autostart,
  };
}

export default function SettingsPage() {
  const [form, setForm] = useState<FormState | null>(null);
  const [keyConfigured, setKeyConfigured] = useState(false);
  const [llmKey, setLlmKey] = useState('');
  const [dropDir, setDropDir] = useState('');
  const [feishuConfigured, setFeishuConfigured] = useState(false);
  const [loadErr, setLoadErr] = useState('');
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [ctxBusy, setCtxBusy] = useState(false);
  const [ctxInstalled, setCtxInstalled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Settings>('/api/settings')
      .then((s) => {
        if (cancelled) return;
        setForm(applySettings(s));
        setKeyConfigured(s.llm_key_configured);
        setDropDir(s.drop_dir);
        setFeishuConfigured(s.feishu_configured);
        setCtxInstalled(s.context_menu_installed);
      })
      .catch((e) => {
        if (!cancelled) setLoadErr(e instanceof Error ? e.message : '设置加载失败');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function validate(): string | null {
    if (!form) return null;
    const port = Number(form.webPort);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return 'Web 端口需为 1-65535 的整数';
    const urls: Array<[string, string]> = [
      ['LLM API base_url', form.llmBaseUrl],
      ['Embedding base_url', form.brainEmbeddingBaseUrl],
      ['大脑 LLM base_url', form.brainLlmBaseUrl],
    ];
    for (const [label, v] of urls) {
      const t = v.trim();
      if (t && !/^https?:\/\//.test(t)) return `${label} 需为 http(s):// 开头的 URL 或留空`;
    }
    return null;
  }

  async function save() {
    if (!form) return;
    const err = validate();
    if (err) {
      setNote({ ok: false, text: err });
      return;
    }
    setSaving(true);
    setNote(null);
    try {
      const body: Record<string, unknown> = {
        web_port: Number(form.webPort),
        auto_start: form.autoStart,
        meeting_enabled: form.sources.meeting,
        system_audio_enabled: form.sources.system_audio,
        clipboard_enabled: form.sources.clipboard,
        feishu_enabled: form.sources.feishu,
        file_enabled: form.sources.file,
        web_enabled: form.sources.web,
        file_dirs: form.fileDirsText.split('\n').map((d) => d.trim()).filter(Boolean),
        compile_enabled: form.compileEnabled,
        compile_auto: form.compileAuto,
        llm_base_url: form.llmBaseUrl,
        llm_model: form.llmModel,
        brain_enabled: form.brainEnabled,
        brain_embedding_base_url: form.brainEmbeddingBaseUrl,
        brain_embedding_model: form.brainEmbeddingModel,
        brain_llm_base_url: form.brainLlmBaseUrl,
        brain_llm_model: form.brainLlmModel,
        autostart: form.autostart,
      };
      // 敏感项：留空 = 保持不变
      if (llmKey.trim()) body.llm_api_key = llmKey.trim();
      if (form.feishuAppId.trim()) body.feishu_app_id = form.feishuAppId.trim();
      if (form.feishuAppSecret.trim()) body.feishu_app_secret = form.feishuAppSecret.trim();
      const r = await api<{ ok: boolean; settings: Settings }>('/api/settings', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setForm(applySettings(r.settings));
      setKeyConfigured(r.settings.llm_key_configured);
      setFeishuConfigured(r.settings.feishu_configured);
      setCtxInstalled(r.settings.context_menu_installed);
      setLlmKey('');
      setNote({ ok: true, text: '设置已保存。Web 端口、编译/大脑 LLM、Embedding 等项重启服务后生效。' });
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setSaving(false);
    }
  }

  /** T-506：安装/卸载资源管理器右键菜单（独立于「保存设置」，即时生效）。 */
  async function toggleCtxMenu(install: boolean) {
    setCtxBusy(true);
    setNote(null);
    try {
      await api<{ ok: boolean }>(`/api/context_menu/${install ? 'install' : 'uninstall'}`, {
        method: 'POST',
        body: '{}',
      });
      setCtxInstalled(install);
      setNote({ ok: true, text: install ? '右键菜单已安装，即刻可在文件夹右键使用。' : '右键菜单已卸载。' });
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : '操作失败' });
    } finally {
      setCtxBusy(false);
    }
  }

  function switchEl(checked: boolean, onChange: (v: boolean) => void, label: string) {
    return (
      <label className="switch">
        <input
          type="checkbox"
          checked={checked}
          aria-label={label}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="switch-track" />
      </label>
    );
  }

  if (loadErr) {
    return (
      <section className="page">
        <h1>设置</h1>
        <p className="msg msg-err">设置加载失败：{loadErr}</p>
      </section>
    );
  }
  if (!form) {
    return (
      <section className="page">
        <h1>设置</h1>
        <p className="status-note">加载中…</p>
      </section>
    );
  }

  return (
    <section className="page">
      <h1>设置</h1>
      <div className="toolbar">
        <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void save()}>
          {saving ? '保存中…' : '保存设置'}
        </button>
        {keyConfigured ? (
          <span className="chip chip-ok">LLM Key 已配置</span>
        ) : (
          <span className="chip chip-warn">LLM Key 未配置</span>
        )}
      </div>
      {note && <p className={`msg ${note.ok ? 'msg-ok' : 'msg-err'}`}>{note.text}</p>}

      <div className="grid2">
        {/* ---- LLM API ---- */}
        <div className="panel">
          <h2 className="panel-title">
            LLM API
            <small>编译与大脑共用的对话模型；Key 写入 .env，保存后不回读</small>
          </h2>
          <div className="field">
            <label className="field-label" htmlFor="set-llm-url">
              base_url
            </label>
            <input
              id="set-llm-url"
              className="input"
              placeholder="https://…/v3"
              value={form.llmBaseUrl}
              onChange={(e) => set('llmBaseUrl', e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-llm-model">
              model
            </label>
            <input
              id="set-llm-model"
              className="input"
              placeholder="模型名"
              value={form.llmModel}
              onChange={(e) => set('llmModel', e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-llm-key">
              API Key
            </label>
            <input
              id="set-llm-key"
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={keyConfigured ? '已配置（输入新值替换，留空保持不变）' : '未配置'}
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
            />
          </div>
        </div>

        {/* ---- Embedding ---- */}
        <div className="panel">
          <h2 className="panel-title">
            Embedding
            <small>大脑向量检索的嵌入模型（cloud 模式走 API，local 模式走本地目录）</small>
          </h2>
          <div className="field">
            <label className="field-label" htmlFor="set-emb-url">
              base_url
            </label>
            <input
              id="set-emb-url"
              className="input"
              placeholder="https://…/v3（local 模式留空）"
              value={form.brainEmbeddingBaseUrl}
              onChange={(e) => set('brainEmbeddingBaseUrl', e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-emb-model">
              model
            </label>
            <input
              id="set-emb-model"
              className="input"
              placeholder="嵌入模型名（local 模式留空）"
              value={form.brainEmbeddingModel}
              onChange={(e) => set('brainEmbeddingModel', e.target.value)}
            />
          </div>
          <p className="status-note">修改后需重启服务并重建大脑索引，已入库向量不会自动重嵌。</p>
        </div>

        {/* ---- 大脑 ---- */}
        <div className="panel">
          <h2 className="panel-title">
            大脑
            <small>知识图谱与问答；LLM 留空时回退编译 LLM 配置</small>
          </h2>
          <div className="set-row">
            <span>启用大脑服务</span>
            {switchEl(form.brainEnabled, (v) => set('brainEnabled', v), '启用大脑服务')}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-brain-llm-url">
              LLM base_url（留空回退编译 LLM）
            </label>
            <input
              id="set-brain-llm-url"
              className="input"
              placeholder="https://…/v3"
              value={form.brainLlmBaseUrl}
              onChange={(e) => set('brainLlmBaseUrl', e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-brain-llm-model">
              LLM model
            </label>
            <input
              id="set-brain-llm-model"
              className="input"
              placeholder="模型名"
              value={form.brainLlmModel}
              onChange={(e) => set('brainLlmModel', e.target.value)}
            />
          </div>
        </div>

        {/* ---- 编译 ---- */}
        <div className="panel">
          <h2 className="panel-title">
            编译
            <small>素材 → 知识条目的提炼管线</small>
          </h2>
          <div className="set-row">
            <span>启用编译服务</span>
            {switchEl(form.compileEnabled, (v) => set('compileEnabled', v), '启用编译服务')}
          </div>
          <div className="set-row">
            <span>自动编译（素材入库即入队）</span>
            {switchEl(form.compileAuto, (v) => set('compileAuto', v), '自动编译')}
          </div>
          <p className="status-note">开关即时生效；LLM 模型配置见「LLM API」分组。</p>
        </div>

        {/* ---- 监听与采集 ---- */}
        <div className="panel">
          <h2 className="panel-title">
            监听目录与采集源
            <small>目录每行一个；开关持久化，重启后按此自启</small>
          </h2>
          <div className="field">
            <label className="field-label" htmlFor="set-file-dirs">
              文件监听目录（每行一个）
            </label>
            <textarea
              id="set-file-dirs"
              className="textarea"
              rows={3}
              placeholder={'D:\\notes\\inbox\nD:\\meeting-records'}
              value={form.fileDirsText}
              onChange={(e) => set('fileDirsText', e.target.value)}
            />
          </div>
          <div className="field">
            <span className="field-label">投递目录（只读）</span>
            <p className="kb-path">{dropDir}</p>
          </div>
          {Object.keys(SOURCE_LABEL).map((name) => (
            <div className="set-row" key={name}>
              <span>{SOURCE_LABEL[name]}采集</span>
              {switchEl(
                form.sources[name] ?? false,
                (v) => set('sources', { ...form.sources, [name]: v }),
                `${SOURCE_LABEL[name]}采集`,
              )}
            </div>
          ))}
          <div className="field" style={{ marginTop: 10 }}>
            <span className="field-label">
              飞书凭据{' '}
              {feishuConfigured ? (
                <span className="chip chip-sm chip-ok">已配置</span>
              ) : (
                <span className="chip chip-sm chip-warn">未配置</span>
              )}
            </span>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-fs-id">
              App ID
            </label>
            <input
              id="set-fs-id"
              className="input"
              type="password"
              autoComplete="off"
              placeholder={feishuConfigured ? '已配置（输入新值替换，留空保持不变）' : '未配置'}
              value={form.feishuAppId}
              onChange={(e) => set('feishuAppId', e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="set-fs-secret">
              App Secret
            </label>
            <input
              id="set-fs-secret"
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={feishuConfigured ? '已配置（输入新值替换，留空保持不变）' : '未配置'}
              value={form.feishuAppSecret}
              onChange={(e) => set('feishuAppSecret', e.target.value)}
            />
          </div>
        </div>

        {/* ---- Web ---- */}
        <div className="panel">
          <h2 className="panel-title">
            Web 控制台
            <small>端口与开机自启；改端口需重启生效</small>
          </h2>
          <div className="field">
            <label className="field-label" htmlFor="set-web-port">
              端口
            </label>
            <input
              id="set-web-port"
              className="input"
              type="number"
              min={1}
              max={65535}
              value={String(form.webPort)}
              onChange={(e) => set('webPort', e.target.value === '' ? '' : Number(e.target.value))}
            />
          </div>
          <div className="set-row">
            <span>启动时自动开始采集</span>
            {switchEl(form.autoStart, (v) => set('autoStart', v), '启动时自动开始采集')}
          </div>
        </div>

        {/* ---- 系统（T-506/T-507） ---- */}
        <div className="panel">
          <h2 className="panel-title">
            系统
            <small>登录自启与资源管理器右键集成（Windows，HKCU 免管理员）</small>
          </h2>
          <div className="set-row">
            <span>开机自动启动（登录后静默运行托盘与控制台）</span>
            {switchEl(form.autostart, (v) => set('autostart', v), '开机自动启动')}
          </div>
          <div className="field">
            <span className="field-label">
              文件夹右键菜单{' '}
              {ctxInstalled ? (
                <span className="chip chip-sm chip-ok">已安装</span>
              ) : (
                <span className="chip chip-sm chip-warn">未安装</span>
              )}
            </span>
          </div>
          <div className="toolbar">
            <button type="button" className="btn" disabled={ctxBusy} onClick={() => void toggleCtxMenu(true)}>
              安装右键菜单
            </button>
            <button type="button" className="btn" disabled={ctxBusy} onClick={() => void toggleCtxMenu(false)}>
              卸载右键菜单
            </button>
          </div>
          <p className="status-note">
            右键任意文件夹可「纳入 KnowSeq 采集」（目录加入监听并开始采集）/「立即结束采集」（停止全部源）；
            自启开关保存后写入注册表，即时生效。
          </p>
        </div>
      </div>
    </section>
  );
}
