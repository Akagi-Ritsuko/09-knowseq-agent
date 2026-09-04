"""极简本地控制台（T-110 REQ-110 / ADR-012）+ 编译集成（T-213 REQ-213）。

FastAPI 本地服务，仅本机监听。提供：采集状态/开关、手动导入（文本/文件）、
网页抓取触发、素材列表、设置（各源开关/监听目录/飞书凭据）、M2 编译
API（状态/触发/review/knowledge 浏览/lint/dedup/enrich）。
完整交互层（问答/图谱/知识管理）属 M4（ADR-010）。
"""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..compile.indexer import update_index
from ..compile.schema import CATEGORIES
from .. import win_integration

DIST_DIR = Path(__file__).resolve().parent / "dist"  # M4 React 前端构建产物（webui build 输出）


def _host_part(value: str) -> str:
    """从 Host/Origin 里取主机名（兼容 localhost:8765、[::1]:8765）。"""
    value = (value or "").strip()
    if value.startswith("["):
        return value[1:value.find("]")].lower()
    return value.rsplit(":", 1)[0].lower() if ":" in value else value.lower()


def _is_local(host: str) -> bool:
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ImportTextReq(BaseModel):
    text: str
    title: str = "手动导入"


class WebIngestReq(BaseModel):
    url: str


class FileDirsAppendReq(BaseModel):
    dir: str


def _check_url(value: str, label: str) -> str:
    """设置页 URL 字段校验：空串放行，否则必须 http(s):// 开头（T-410）。"""
    v = value.strip()
    if v and not v.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail=f"{label} 需为 http(s):// 开头的 URL 或留空")
    return v


class SettingsReq(BaseModel):
    web_port: int | None = None
    auto_start: bool | None = None
    meeting_enabled: bool | None = None
    system_audio_enabled: bool | None = None
    clipboard_enabled: bool | None = None
    feishu_enabled: bool | None = None
    file_enabled: bool | None = None
    web_enabled: bool | None = None
    file_dirs: list[str] | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    compile_enabled: bool | None = None
    compile_auto: bool | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    # T-410：大脑配置节 + LLM API Key（只写不回读）
    brain_enabled: bool | None = None
    brain_embedding_base_url: str | None = None
    brain_embedding_model: str | None = None
    brain_llm_base_url: str | None = None
    brain_llm_model: str | None = None
    llm_api_key: str | None = None
    # T-507 REQ-507：登录 Windows 自启 run.py（写入即同步 HKCU Run 键）
    autostart: bool | None = None


class CompileTriggerReq(BaseModel):
    scope: str = "all"          # all | path
    path: str | None = None     # scope=path 时的 inbox 相对路径


class ReviewResolveReq(BaseModel):
    id: str
    note: str | None = None


class BrainIndexReq(BaseModel):
    rebuild: bool = False


class MaterialMarkReq(BaseModel):
    path: str
    compiled: bool


class KnowledgeWriteReq(BaseModel):
    path: str
    content: str


class BrainQueryReq(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = 10


def create_app(config, inbox, manager, compile_mgr=None, brain_mgr=None) -> FastAPI:
    app = FastAPI(title="KnowSeq Agent", version="0.1.0")

    # ---- 本机访问限制（REQ-110）----
    # 只校验 Host 不够：跨站表单/multipart 的 Host 也是本机，
    # 所以带 Origin 且 Origin 不是本机的请求（simple request）一并拒绝。
    # [ADR-016 决策 4 · 方案 B sidecar 演进口子] 迁移方案 B（壳内嵌 dist 经 Tauri
    # 自定义协议访问）时 WebView Origin 变为 `http://tauri.localhost`，需在此放行
    # （origin_host == "tauri.localhost" 视为本机）；现方案 A（壳直接加载
    # http://127.0.0.1:8765）Origin 即本机，校验零改动。
    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if not _is_local(_host_part(request.headers.get("host", ""))):
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            try:
                origin_host = urlsplit(origin).hostname or ""
            except ValueError:
                origin_host = ""
            if not _is_local(origin_host):
                return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
        return await call_next(request)

    # ---- 状态与开关 ----
    @app.get("/api/status")
    def status():
        return {
            "manager": manager.get_status(),
            "materials": {"count": len(inbox.list_materials())},
        }

    @app.post("/api/start")
    def start():
        manager.start_all()
        return {"ok": True, "status": manager.get_status()}

    @app.post("/api/stop")
    def stop():
        manager.stop_all()
        return {"ok": True, "status": manager.get_status()}

    @app.post("/api/start/{name}")
    def start_one(name: str):
        try:
            manager.start_one(name)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"ok": True, "status": manager.get_status()}

    @app.post("/api/stop/{name}")
    def stop_one(name: str):
        try:
            manager.stop_one(name)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"ok": True, "status": manager.get_status()}

    # ---- Windows 集成（T-506 REQ-506：右键菜单触发入口）----
    @app.post("/api/file_dirs/append")
    def file_dirs_append(req: FileDirsAppendReq):
        """右键「纳入采集」：追加监听目录并持久化；file 源 running 时重启使其生效
        （FileSource 仅在 start() 时 schedule watched_dirs，见 ADR-006 实现约束）。"""
        raw = (req.dir or "").strip().strip('"')
        if not raw:
            raise HTTPException(status_code=422, detail="目录不能为空")
        d = Path(raw)
        if not d.is_dir():
            raise HTTPException(status_code=422, detail=f"目录不存在：{raw}")
        stored = str(d)
        dirs = [str(x) for x in (config.get("sources.file.dirs") or [])]
        if not any(os.path.normcase(x) == os.path.normcase(stored) for x in dirs):
            dirs.append(stored)
            config.set("sources.file.dirs", dirs)
            config.save()
        restarted = False
        if manager.get("file").status == "running":
            manager.stop_one("file")
            manager.start_one("file")
            restarted = True
        return {"ok": True, "dir": stored, "dirs": dirs, "restarted": restarted}

    @app.post("/api/stop_all")
    def stop_all():
        """右键「立即结束采集」：停止全部采集源（与 /api/stop 同义，语义命名入口）。"""
        manager.stop_all()
        return {"ok": True, "status": manager.get_status()}

    @app.post("/api/context_menu/install")
    def context_menu_install():
        try:
            win_integration.install_context_menu()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"注册表写入失败：{e}") from e
        return {"ok": True, "installed": True}

    @app.post("/api/context_menu/uninstall")
    def context_menu_uninstall():
        try:
            win_integration.uninstall_context_menu()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"注册表删除失败：{e}") from e
        return {"ok": True, "installed": False}

    # ---- 手动导入（REQ-109） ----
    @app.post("/api/import")
    def import_text(req: ImportTextReq):
        path = inbox.write_material("manual", req.title, req.text,
                                    meta={"imported_by": "console"})
        if path is None:
            raise HTTPException(status_code=400, detail="内容为空或与已有素材重复")
        return {"ok": True, "path": str(path.relative_to(inbox.root))}

    @app.post("/api/import/file")
    async def import_file(file: UploadFile = File(...)):
        data = await file.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gbk", errors="replace")
        path = inbox.write_material("manual", file.filename or "手动上传", text,
                                    meta={"file": file.filename or ""})
        if path is None:
            raise HTTPException(status_code=400, detail="内容为空或与已有素材重复")
        return {"ok": True, "path": str(path.relative_to(inbox.root))}

    # ---- 网页抓取（REQ-108） ----
    @app.post("/api/web/ingest")
    def web_ingest(req: WebIngestReq):
        src = manager.get("web")
        if not src.enabled():
            raise HTTPException(status_code=403, detail="网页采集未启用")
        rel, err = src.ingest(req.url)
        if err:
            raise HTTPException(status_code=400, detail=err)
        return {"ok": True, "path": rel}

    # ---- 飞书云文档导入（REQ-106） ----
    @app.post("/api/feishu/doc")
    def feishu_doc(req: WebIngestReq):
        src = manager.get("feishu")
        rel, err = src.import_doc(req.url)
        if err:
            raise HTTPException(status_code=400, detail=err)
        return {"ok": True, "path": rel}

    # ---- 素材（REQ-408：列表状态 / 标记 / 预览） ----
    @app.get("/api/materials")
    def materials(source: str | None = None):
        return {"materials": inbox.list_materials(source)}

    @app.post("/api/materials/mark")
    def materials_mark(req: MaterialMarkReq):
        if not inbox.mark_compiled(req.path, req.compiled):
            raise HTTPException(status_code=404, detail=f"素材不存在：{req.path}")
        return {"ok": True, "path": req.path, "compiled": req.compiled}

    @app.get("/api/materials/content")
    def materials_content(path: str):
        mat = inbox.read_material(path)
        if mat is None:
            raise HTTPException(status_code=404, detail=f"素材不存在：{path}")
        return mat

    # ---- 设置 ----
    @app.get("/api/settings")
    def settings():
        return {
            "web_port": config.get("web.port", 8765),
            "auto_start": config.get("web.auto_start", True),
            "sources": {
                "meeting": config.get("sources.meeting.enabled", False),
                "system_audio": config.get("sources.system_audio.enabled", False),
                "clipboard": config.get("sources.clipboard.enabled", True),
                "feishu": config.get("sources.feishu.enabled", False),
                "file": config.get("sources.file.enabled", True),
                "web": config.get("sources.web.enabled", True),
            },
            "file_dirs": config.get("sources.file.dirs") or [],
            "drop_dir": str(config.drop_dir),
            "feishu_configured": bool(config.secret("FEISHU_APP_ID")),
            "compile": {
                "enabled": config.get("compile.enabled", True),
                "auto": config.get("compile.auto", True),
                "llm_base_url": config.get("compile.llm.base_url", ""),
                "llm_model": config.get("compile.llm.model", ""),
                "llm_key_configured": bool(config.secret("LLM_API_KEY")),
            },
            # T-410：大脑配置节（LLM Key 恒不回读，仅返回已设置标志）
            "brain": {
                "enabled": config.get("brain.enabled", False),
                "embedding_base_url": config.get("brain.embedding.base_url", ""),
                "embedding_model": config.get("brain.embedding.model", ""),
                "llm_base_url": config.get("brain.llm.base_url", ""),
                "llm_model": config.get("brain.llm.model", ""),
            },
            "llm_key_configured": bool(config.secret("LLM_API_KEY")),
            # T-506/T-507：Windows 集成状态（installed 以注册表实际状态为准）
            "autostart": config.get("app.autostart", False),
            "autostart_installed": win_integration.autostart_installed(),
            "context_menu_installed": win_integration.context_menu_installed(),
        }

    @app.post("/api/settings")
    def save_settings(req: SettingsReq):
        # 校验先行（非法值 422，不做部分写入）
        if req.web_port and not (1 <= int(req.web_port) <= 65535):
            raise HTTPException(status_code=422, detail="Web 端口需为 1-65535 的整数")
        if req.llm_base_url is not None:
            _check_url(req.llm_base_url, "LLM API base_url")
        if req.brain_llm_base_url is not None:
            _check_url(req.brain_llm_base_url, "大脑 LLM base_url")
        if req.brain_embedding_base_url is not None:
            _check_url(req.brain_embedding_base_url, "Embedding base_url")
        if req.web_port:
            config.set("web.port", int(req.web_port))
        if req.auto_start is not None:
            config.set("web.auto_start", bool(req.auto_start))
        for key, val in {
            "meeting": req.meeting_enabled,
            "system_audio": req.system_audio_enabled,
            "clipboard": req.clipboard_enabled,
            "feishu": req.feishu_enabled,
            "file": req.file_enabled,
            "web": req.web_enabled,
        }.items():
            if val is not None:
                config.set(f"sources.{key}.enabled", bool(val))
        if req.file_dirs is not None:
            config.set("sources.file.dirs", [d for d in req.file_dirs if d.strip()])
        if req.feishu_app_id:
            config.set_env("FEISHU_APP_ID", req.feishu_app_id.strip())
        if req.feishu_app_secret:
            config.set_env("FEISHU_APP_SECRET", req.feishu_app_secret.strip())
        if req.compile_enabled is not None:
            config.set("compile.enabled", bool(req.compile_enabled))
        if req.compile_auto is not None:
            config.set("compile.auto", bool(req.compile_auto))
        if req.llm_base_url is not None:
            config.set("compile.llm.base_url", req.llm_base_url.strip())
        if req.llm_model is not None:
            config.set("compile.llm.model", req.llm_model.strip())
        # T-410：大脑配置节 + LLM API Key（敏感项走 .env，不入 config.yaml）
        if req.brain_enabled is not None:
            config.set("brain.enabled", bool(req.brain_enabled))
        if req.brain_embedding_base_url is not None:
            config.set("brain.embedding.base_url", req.brain_embedding_base_url.strip())
        if req.brain_embedding_model is not None:
            config.set("brain.embedding.model", req.brain_embedding_model.strip())
        if req.brain_llm_base_url is not None:
            config.set("brain.llm.base_url", req.brain_llm_base_url.strip())
        if req.brain_llm_model is not None:
            config.set("brain.llm.model", req.brain_llm_model.strip())
        if req.llm_api_key:
            config.set_env("LLM_API_KEY", req.llm_api_key.strip())
        # T-507：自启注册表先行（失败 500 时 config 未变，保持"不做部分写入"）
        if req.autostart is not None:
            try:
                win_integration.set_autostart(bool(req.autostart))
            except OSError as e:
                raise HTTPException(status_code=500, detail=f"开机自启写入失败：{e}") from e
            config.set("app.autostart", bool(req.autostart))
        config.save()
        return {"ok": True, "settings": settings()}

    # ---- 编译（REQ-213）----
    def _require_compile():
        if compile_mgr is None:
            raise HTTPException(status_code=404, detail="编译服务未启用")

    @app.get("/api/compile/status")
    def compile_status():
        _require_compile()
        return compile_mgr.status()

    @app.post("/api/compile/trigger")
    def compile_trigger(req: CompileTriggerReq):
        _require_compile()
        if req.scope == "path":
            return {"ok": True, "scope": "path",
                    "triggered": compile_mgr.trigger_path(req.path or "")}
        return {"ok": True, "scope": "all", "triggered": compile_mgr.trigger_all()}

    @app.get("/api/compile/reviews")
    def compile_reviews():
        _require_compile()
        return {"reviews": compile_mgr.reviews.list("open")}

    @app.post("/api/compile/reviews/resolve")
    def reviews_resolve(req: ReviewResolveReq):
        _require_compile()
        if not compile_mgr.reviews.resolve(req.id, req.note):
            raise HTTPException(status_code=404,
                                detail=f"review 不存在或已解决：{req.id}")
        return {"ok": True}

    # ---- 知识管理（REQ-409）----
    def _resolve_entry(path: str) -> Path:
        """条目路径防穿越解析：resolve 后必须仍在 knowledge 目录内且存在。"""
        kd = config.knowledge_dir
        if not kd.is_dir():
            raise HTTPException(status_code=404, detail="knowledge 目录不存在")
        target = (kd / path).resolve()
        if kd.resolve() not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="条目不存在")
        return target

    @app.get("/api/knowledge")
    def knowledge(path: str | None = None):
        if path:
            target = _resolve_entry(path)
            return {"path": path, "content": target.read_text(encoding="utf-8")}
        kd = config.knowledge_dir
        entries: list[dict] = []
        for cat in CATEGORIES:
            cat_dir = kd / cat
            if not cat_dir.is_dir():
                continue
            for mdf in sorted(cat_dir.glob("*.md")):
                entries.append({"type": cat, "slug": mdf.stem,
                                "path": f"{cat}/{mdf.name}"})
        return {"entries": entries}

    @app.put("/api/knowledge")
    def knowledge_put(req: KnowledgeWriteReq):
        """条目源码写回 + index.md 重建（防穿越校验同 GET）。"""
        target = _resolve_entry(req.path)
        target.write_text(req.content, encoding="utf-8")
        return {"ok": True, "path": req.path,
                "index_updated": update_index(config.knowledge_dir)}

    @app.delete("/api/knowledge")
    def knowledge_delete(path: str):
        """删除条目文件 + index.md 重建 + 大脑索引一致性（brain.remove）。"""
        target = _resolve_entry(path)
        target.unlink()
        index_updated = update_index(config.knowledge_dir)
        brain_res = (brain_mgr.remove(path.replace("\\", "/"))
                     if brain_mgr is not None else None)
        return {"ok": True, "path": path, "index_updated": index_updated,
                "brain": brain_res}

    @app.post("/api/compile/lint")
    def compile_lint():
        _require_compile()
        try:
            return {"issues": compile_mgr.run_lint()}
        except Exception as e:  # noqa: BLE001 — 失败返回 400 细节，不改写未捕获栈
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/compile/dedup")
    def compile_dedup():
        _require_compile()
        try:
            return compile_mgr.run_dedup()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/compile/enrich")
    def compile_enrich(dry_run: bool = False):
        _require_compile()
        try:
            return compile_mgr.run_enrich(dry_run=dry_run)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)) from e

    # ---- 大脑层（REQ-306）----
    def _require_brain():
        if brain_mgr is None or not brain_mgr.status().get("ready"):
            raise HTTPException(status_code=400,
                                detail=brain_mgr.status()["last_error"]
                                if brain_mgr and brain_mgr.status()["last_error"]
                                else "大脑未启用（brain.enabled / embedding 配置 / lightrag-hku）")

    @app.get("/api/brain/status")
    def brain_status():
        if brain_mgr is None:
            raise HTTPException(status_code=404, detail="大脑服务未启用")
        return brain_mgr.status()

    @app.post("/api/brain/index")
    def brain_index(req: BrainIndexReq):
        _require_brain()
        return brain_mgr.index(config.knowledge_dir, full_rebuild=req.rebuild)

    @app.post("/api/brain/query")
    def brain_query(req: BrainQueryReq):
        _require_brain()
        return brain_mgr.ask(req.query, mode=req.mode, top_k=req.top_k)

    @app.get("/api/brain/search")
    def brain_search(q: str, top_k: int = 10):
        _require_brain()
        return {"hits": brain_mgr.search(q, top_k=top_k)}

    @app.get("/api/brain/graph")
    def brain_graph():
        _require_brain()
        return brain_mgr.graph()

    # ---- 静态前端（M4 REQ-411：旧 static 已下线，dist 托管 + SPA fallback）----
    dist_index = DIST_DIR / "index.html"
    if dist_index.exists():
        if (DIST_DIR / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (DIST_DIR / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(DIST_DIR):
                return FileResponse(candidate)
            return FileResponse(dist_index)  # SPA 前端路由兜底

    return app
