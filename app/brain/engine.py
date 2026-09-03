"""大脑引擎（M3 REQ-301）：LightRAG 同步门面。

LightRAG（lightrag-hku）是 asyncio 库。按 M3 决策 D1，本模块在内部维护
一个专用后台事件循环线程，所有 rag 操作经 ``run_coroutine_threadsafe``
提交到该 loop，对外提供**同步**接口——不改变采集/编译层的 threading 风格。

对外能力（REQ-302~305）：
- index(knowledge_dir, full_rebuild=False)：五类条目增量索引（rel 路径 doc_id
  + 内容哈希幂等，状态落 ``index_state.json``）
- search(query, top_k)：naive 向量检索，返回片段 + 来源文件
- ask(query, mode)：带引用问答（LLM 生成 + contexts 来源）
- graph()：knowledge 图谱导出（nodes/edges JSON，vis-network 兼容）

LLM/embedding 均走 OpenAI 兼容端点（D3）：embedding 用 ``brain.embedding.*``，
问答 LLM 缺省复用 ``compile.llm.*``；Key 复用 .env ``LLM_API_KEY``（不落日志）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import threading
from functools import partial
from pathlib import Path

from ..compile.schema import CATEGORIES
from ..config import Config

try:
    from lightrag import LightRAG
    from lightrag.base import QueryParam
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc

    _LIGHTRAG_OK = True
except Exception:  # pragma: no cover - 依赖缺失时整模块降级
    _LIGHTRAG_OK = False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BrainEngine:
    """LightRAG 大脑引擎（同步门面）。start() 前不做任何网络请求。"""

    def __init__(self, config: Config):
        self.config = config
        self._working_dir = config.knowledge_dir.parent / ".knowseq" / "brain"
        self._index_state = self._working_dir / "index_state.json"
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._rag: LightRAG | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._embedding_dim = int(config.get("brain.embedding.dim", 0) or 0)

    # ── 生命周期 ────────────────────────────────────────────────
    def is_ready(self) -> bool:
        """嵌入/LLM 配置齐备且引擎已启动（无锁：简单读，供线程内调用）。"""
        return self._rag is not None and self._last_error is None

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": bool(self.config.get("brain.enabled", False)),
                "ready": self._rag is not None and self._last_error is None,
                "lightrag_installed": _LIGHTRAG_OK,
                "embedding_configured": self._embedding_ready(),
                "embedding_mode": self._embed_mode(),
                "working_dir": str(self._working_dir),
                "embedding_dim": self._embedding_dim,
                "last_error": self._last_error,
            }

    def start(self) -> None:
        """启动引擎（构造 LightRAG + 初始化存储；local 模式加载本地模型）。"""
        if self._rag is not None:
            return
        if not _LIGHTRAG_OK:
            self._last_error = "lightrag-hku 未安装（pip install lightrag-hku）"
            return
        if not (self._llm_base() and self._llm_model()
                and self.config.secret("LLM_API_KEY")):
            self._last_error = ("brain 未配置：需 LLM base_url/model"
                                "（compile.llm 或 brain.llm）与 .env LLM_API_KEY")
            return
        if not self._embedding_ready():
            self._last_error = self._embedding_hint()
            return
        self._ensure_loop()
        try:
            self._rag = self._run(self._build_rag)
        except Exception as e:  # noqa: BLE001 — 构造失败保留错误供 status 展示
            with self._lock:
                self._last_error = f"brain 启动失败: {e}"
            self._rag = None

    def stop(self) -> None:
        rag, loop = self._rag, self._loop
        self._rag = None
        if rag is not None:
            try:
                self._run_safe(rag.finalize_storages, timeout=30)
            except Exception:  # noqa: BLE001 — 清理失败不阻断退出
                pass
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if self._thread:
                self._thread.join(timeout=5)
        self._thread = None
        self._loop = None
        self._loop_ready.clear()

    # ── 后台事件循环线程（M3 决策 D1）───────────────────────────
    def _ensure_loop(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._loop_ready.clear()
            self._thread = threading.Thread(
                target=self._loop_main, name="brain-loop", daemon=True)
            self._thread.start()
        self._loop_ready.wait(timeout=10)
        if not self._loop_ready.is_set():
            raise RuntimeError("brain 事件循环线程启动超时")

    def _loop_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def _run(self, coro_factory, timeout: float | None = 900) -> object:
        """在 brain loop 中运行协程工厂并同步等待结果。"""
        self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return fut.result(timeout=timeout)

    def _run_safe(self, coro_factory, timeout: float | None = 900) -> object | None:
        try:
            return self._run(coro_factory, timeout=timeout)
        except Exception:  # noqa: BLE001 — 调用方兜底
            return None

    # ── 配置推导 ────────────────────────────────────────────────
    def _embed_mode(self) -> str:
        return self.config.get("brain.embedding.mode", "cloud") or "cloud"

    def _embed_base(self) -> str:
        return self.config.get("brain.embedding.base_url", "") or ""

    def _embed_model(self) -> str:
        return self.config.get("brain.embedding.model", "") or ""

    def _embed_model_dir(self) -> Path | None:
        p = self.config.get("brain.embedding.model_dir", "") or ""
        if not p:
            return None
        path = Path(p)
        if not path.is_absolute():
            path = Path(self.config.knowledge_dir).parent / path
        return path

    def _embedding_ready(self) -> bool:
        if self._embed_mode() == "local":
            d = self._embed_model_dir()
            return d is not None and d.is_dir()
        return bool(self._embed_base() and self._embed_model()
                    and self.config.secret("LLM_API_KEY"))

    def _embedding_hint(self) -> str:
        if self._embed_mode() == "local":
            return "本地 embedding 模型目录不存在或未配置（brain.embedding.model_dir）"
        return "brain 未配置：需 brain.embedding.base_url/model 与 .env LLM_API_KEY"

    def _llm_base(self) -> str:
        return (self.config.get("brain.llm.base_url", "")
                or self.config.get("compile.llm.base_url", "") or "")

    def _llm_model(self) -> str:
        return (self.config.get("brain.llm.model", "")
                or self.config.get("compile.llm.model", "") or "")

    async def _build_rag(self) -> LightRAG:
        """在 loop 内构造 LightRAG（embedding 按 mode 分支 + 存储初始化）。"""
        if self._embed_mode() == "local":
            return await self._build_rag_local()
        return await self._build_rag_cloud()

    async def _build_rag_cloud(self) -> LightRAG:
        api_key = self.config.secret("LLM_API_KEY")
        embed_base, embed_model = self._embed_base(), self._embed_model()
        if self._embedding_dim <= 0:  # 由返回向量推断维度
            probe = await openai_embed(
                ["维度探测"], model=embed_model, base_url=embed_base, api_key=api_key)
            self._embedding_dim = int(len(probe[0]))
        embedding_func = EmbeddingFunc(
            embedding_dim=self._embedding_dim,
            max_token_size=8_192,
            func=partial(openai_embed, model=embed_model,
                         base_url=embed_base, api_key=api_key),
        )
        return await self._rag_factory(embedding_func, api_key)

    async def _build_rag_local(self) -> LightRAG:
        from sentence_transformers import SentenceTransformer

        model_dir = self._embed_model_dir()
        model = await asyncio.to_thread(SentenceTransformer, str(model_dir))
        dim_getter = getattr(model, "get_embedding_dimension",
                             model.get_sentence_embedding_dimension)
        self._embedding_dim = int(dim_getter())

        async def local_embed(texts, **kw):
            return await asyncio.to_thread(
                model.encode, list(texts),
                normalize_embeddings=True, show_progress_bar=False)

        embedding_func = EmbeddingFunc(
            embedding_dim=self._embedding_dim, max_token_size=512, func=local_embed)
        return await self._rag_factory(embedding_func)

    def _make_llm_func(self):
        """LightRAG 的 llm_model_func：显式绑定 base_url/model/api_key。

        LightRAG 自带 openai_complete 不接受 model 参数（从 hashing_kv 全局配置
        读取），partial 传入会与 openai_complete_if_cache 位置参数冲突；故自定义
        包装直接调用 openai_complete_if_cache。
        """
        api_key = self.config.secret("LLM_API_KEY")
        model = self._llm_model()
        base_url = self._llm_base()

        async def llm_func(prompt, system_prompt=None, history_messages=None, **kw):
            return await openai_complete_if_cache(
                model, prompt, system_prompt=system_prompt,
                history_messages=history_messages or [],
                base_url=base_url, api_key=api_key)

        return llm_func

    async def _rag_factory(self, embedding_func) -> LightRAG:
        self._working_dir.mkdir(parents=True, exist_ok=True)
        rag = LightRAG(
            working_dir=str(self._working_dir),
            embedding_func=embedding_func,
            llm_model_func=self._make_llm_func(),
            llm_model_name=self._llm_model(),
            chunk_token_size=1200,
        )
        await rag.initialize_storages()
        return rag

    # ── REQ-302 索引 ────────────────────────────────────────────
    def index(self, knowledge_dir: Path, *, full_rebuild: bool = False) -> dict:
        """五类条目增量索引；full_rebuild 清空工作目录全量重建。"""
        kd = Path(knowledge_dir)
        docs = self._collect_docs(kd)
        if full_rebuild:
            self.stop()
            shutil.rmtree(self._working_dir, ignore_errors=True)
            self.start()
            state: dict[str, str] = {}
        else:
            state = self._load_state()
        to_insert = [(rel, text) for rel, text in docs
                     if state.get(rel) != _sha256(text)]
        if to_insert:
            rag = self._require_rag()
            texts = [t for _, t in to_insert]
            rels = [r for r, _ in to_insert]
            self._run_safe(lambda: rag.ainsert(texts, ids=rels, file_paths=rels),
                           timeout=1800)
        for rel, text in to_insert:
            state[rel] = _sha256(text)
        self._save_state(state)
        return {"scanned": len(docs), "inserted": len(to_insert),
                "skipped": len(docs) - len(to_insert)}

    def _collect_docs(self, kd: Path) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for cat in CATEGORIES:
            cat_dir = kd / cat
            if not cat_dir.is_dir():
                continue
            for mdf in sorted(cat_dir.glob("*.md")):
                try:
                    text = mdf.read_text(encoding="utf-8")
                except OSError:
                    continue
                out.append((f"{cat}/{mdf.name}", text))
        return out

    def _require_rag(self) -> LightRAG:
        if not self.is_ready():
            raise RuntimeError(self._last_error or "brain 引擎未启动")
        return self._rag

    def _load_state(self) -> dict[str, str]:
        try:
            return json.loads(self._index_state.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        self._index_state.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_state.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self._index_state)

    # ── REQ-303 语义检索 ────────────────────────────────────────
    def search(self, query: str, top_k: int = 10) -> list[dict]:
        rag = self._require_rag()
        param = QueryParam(mode="naive", top_k=int(top_k), only_need_context=True)
        data = self._run_safe(lambda: rag.aquery_data(query, param), timeout=600)
        hits = self._extract_hits(data or {}, top_k=int(top_k))
        return hits

    # ── REQ-304 带引用问答 ──────────────────────────────────────
    def ask(self, query: str, mode: str = "hybrid", top_k: int = 10) -> dict:
        rag = self._require_rag()
        param = QueryParam(mode=mode, top_k=int(top_k))
        result = self._run_safe(lambda: rag.aquery_llm(query, param), timeout=600)
        result = result or {}
        llm_resp = result.get("llm_response") or {}
        answer = llm_resp.get("content") or ""
        contexts = self._extract_hits(result.get("data") or {}, top_k=int(top_k))
        return {"answer": answer, "contexts": contexts, "mode": mode}

    # ── REQ-305 图谱导出 ────────────────────────────────────────
    def graph(self, max_nodes: int = 500) -> dict:
        rag = self._require_rag()
        labels = self._run_safe(rag.get_graph_labels, timeout=120)
        if not labels:
            return {"nodes": [], "edges": []}
        if isinstance(labels, str):
            labels = [labels]
        nodes: dict[str, dict] = {}
        edges: dict[str, dict] = {}
        for label in labels[:20]:
            kg = self._run_safe(
                lambda l=label: rag.get_knowledge_graph(l, max_nodes=max_nodes),
                timeout=300)
            if not kg:
                continue
            for n in kg.nodes or []:
                nodes[n.id] = {"id": n.id, "label": n.id,
                               "type": (n.labels or ["entity"])[0]}
            for e in kg.edges or []:
                key = (e.source, e.target, e.type)
                edges.setdefault(key, {"source": e.source, "target": e.target,
                                       "relation": e.type})
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    # ── 结果解析（容错：LightRAG 返回含顶层 data 嵌套，1.5.7 兼容）──
    @staticmethod
    def _extract_hits(result: dict, top_k: int) -> list[dict]:
        data = result.get("data") or result  # 兼容 {data:{chunks}} 与平铺
        chunks = data.get("chunks") or []
        hits: list[dict] = []
        for item in chunks:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or ""
            file_path = (item.get("full_doc_id")
                         or _rel_from_chunk_id(item.get("chunk_id"))
                         or item.get("file_path")
                         or item.get("source_id") or "")
            if not content:
                continue
            hits.append({"content": content[:800], "file_path": str(file_path)})
            if len(hits) >= top_k:
                break
        return hits


_CHUNK_ID_TAIL = re.compile(r"-chunk-\d+$")


def _rel_from_chunk_id(chunk_id: object) -> str:
    """从 LightRAG chunk_id（``{rel}-chunk-NNN``）反解 knowledge 相对路径。

    lightrag-hku 2.x 在入队时把 file_path 规范化为 basename
    （utils_pipeline.normalize_document_file_path），而来源跳转需要完整
    相对路径；索引时以 rel 作为 doc id，chunk_id 前缀即 rel。
    """
    if not chunk_id:
        return ""
    return _CHUNK_ID_TAIL.sub("", str(chunk_id))
