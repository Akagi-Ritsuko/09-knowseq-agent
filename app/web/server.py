"""极简本地控制台（T-110 REQ-110 / ADR-012）。

FastAPI 本地服务，仅本机监听。提供：采集状态/开关、手动导入（文本/文件）、
网页抓取触发、素材列表、设置（各源开关/监听目录/飞书凭据）。
完整交互层（问答/图谱/知识管理）属 M4（ADR-010）。
"""
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ImportTextReq(BaseModel):
    text: str
    title: str = "手动导入"


class WebIngestReq(BaseModel):
    url: str


class SettingsReq(BaseModel):
    web_port: int | None = None
    auto_start: bool | None = None
    screen_enabled: bool | None = None
    clipboard_enabled: bool | None = None
    feishu_enabled: bool | None = None
    file_enabled: bool | None = None
    web_enabled: bool | None = None
    file_dirs: list[str] | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None


def create_app(config, inbox, manager) -> FastAPI:
    app = FastAPI(title="KnowSeq Agent", version="0.1.0")

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

    # ---- 素材 ----
    @app.get("/api/materials")
    def materials(source: str | None = None):
        return {"materials": inbox.list_materials(source)}

    # ---- 设置 ----
    @app.get("/api/settings")
    def settings():
        return {
            "web_port": config.get("web.port", 8765),
            "auto_start": config.get("web.auto_start", True),
            "sources": {
                "screen": config.get("sources.screen.enabled", False),
                "clipboard": config.get("sources.clipboard.enabled", True),
                "feishu": config.get("sources.feishu.enabled", False),
                "file": config.get("sources.file.enabled", True),
                "web": config.get("sources.web.enabled", True),
            },
            "file_dirs": config.get("sources.file.dirs") or [],
            "drop_dir": str(config.drop_dir),
            "feishu_configured": bool(config.secret("FEISHU_APP_ID")),
        }

    @app.post("/api/settings")
    def save_settings(req: SettingsReq):
        if req.web_port:
            config.set("web.port", int(req.web_port))
        if req.auto_start is not None:
            config.set("web.auto_start", bool(req.auto_start))
        for key, val in {
            "screen": req.screen_enabled,
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
        config.save()
        return {"ok": True, "settings": settings()}

    # ---- 静态前端 ----
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
