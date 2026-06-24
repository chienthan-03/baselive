import logging
import os
from pathlib import Path
from typing import Generator, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.core.models import BoundaryResult
from src.db.database import Database
from src.observability import health as health_mod
from src.engine.llm_gate import LLMGate
from src.ingestion.orchestrator import (
    OrchestratorService,
    PlatformNotSupportedError,
    StreamAlreadyRunningError,
)
from src.ingestion.stream_manager import StreamManager
from src.ingestion.worker_node import CapacityError

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    class _FlushingHandler(logging.StreamHandler):
        def emit(self, record: logging.LogRecord) -> None:
            super().emit(record)
            self.flush()

    handler = _FlushingHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


_configure_logging()

# --- Dependency ---

def get_db() -> Generator:
    db = Database()
    db.init_db()
    try:
        yield db
    finally:
        db.close()

_llm_gate = LLMGate()
_orchestrator = OrchestratorService()
_stream_manager = StreamManager(orchestrator=_orchestrator)


def get_orchestrator() -> OrchestratorService:
    return _orchestrator


def get_stream_manager() -> StreamManager:
    return _stream_manager


def _check_db_ok(db: Database) -> bool:
    try:
        db.conn.execute("SELECT 1")
        return True
    except Exception:
        return False

# --- Pydantic Schemas ---

class AdjustRequest(BaseModel):
    start_pts: float
    end_pts: float

class RejectRequest(BaseModel):
    reason: str

class StartStreamRequest(BaseModel):
    url: str
    stream_id: str
    platform: str = "tiktok"

def _ai_boundaries(h: dict) -> tuple[float, float]:
    ai_start = h["ai_start_pts"] if h.get("ai_start_pts") is not None else h["start_pts"]
    ai_end = h["ai_end_pts"] if h.get("ai_end_pts") is not None else h["end_pts"]
    return ai_start, ai_end

# --- Routers ---

router = APIRouter()

@router.get("/")
def serve_dashboard():
    """Serve the main SPA HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard is loading...</h1>")

@router.get("/api/highlights")
def get_highlights(
    type: Optional[str] = Query(None, description="Filter by highlight type: DRAFT or FINAL"),
    stream_id: Optional[str] = Query(None, description="Filter by stream ID"),
    db: Database = Depends(get_db),
):
    """Return highlights ordered by newest first, optionally filtered."""
    return db.get_highlights(type=type, stream_id=stream_id)

@router.post("/api/highlights/{highlight_id}/approve")
def approve_highlight(highlight_id: int, db: Database = Depends(get_db)):
    """Mark a highlight as APPROVED."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    ai_start, ai_end = _ai_boundaries(h)
    db.insert_feedback(
        highlight_id=highlight_id,
        stream_id=h["stream_id"],
        action="ACCEPT",
        ai_start_pts=ai_start,
        ai_end_pts=ai_end,
        ai_score=h["score"],
        editor_start_pts=h["start_pts"],
        editor_end_pts=h["end_pts"],
        start_delta_sec=0.0,
        end_delta_sec=0.0,
        content_type=h.get("content_type"),
    )
    db.update_status(highlight_id, "APPROVED")
    return {"id": highlight_id, "status": "APPROVED"}

@router.post("/api/highlights/{highlight_id}/reject")
def reject_highlight(
    highlight_id: int,
    body: RejectRequest,
    db: Database = Depends(get_db),
):
    """Mark a highlight as REJECTED."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    ai_start, ai_end = _ai_boundaries(h)
    db.insert_feedback(
        highlight_id=highlight_id,
        stream_id=h["stream_id"],
        action="REJECT",
        ai_start_pts=ai_start,
        ai_end_pts=ai_end,
        ai_score=h["score"],
        editor_start_pts=h["start_pts"],
        editor_end_pts=h["end_pts"],
        reject_reason=body.reason,
        content_type=h.get("content_type"),
    )
    db.update_status(highlight_id, "REJECTED")
    return {"id": highlight_id, "status": "REJECTED"}

@router.post("/api/highlights/{highlight_id}/adjust")
def adjust_highlight(highlight_id: int, body: AdjustRequest, db: Database = Depends(get_db)):
    """Adjust the start/end timestamps of a highlight."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    ai_start, ai_end = _ai_boundaries(h)
    start_delta = body.start_pts - ai_start
    end_delta = body.end_pts - ai_end
    db.insert_feedback(
        highlight_id=highlight_id,
        stream_id=h["stream_id"],
        action="MODIFY",
        ai_start_pts=ai_start,
        ai_end_pts=ai_end,
        ai_score=h["score"],
        editor_start_pts=body.start_pts,
        editor_end_pts=body.end_pts,
        start_delta_sec=start_delta,
        end_delta_sec=end_delta,
        content_type=h.get("content_type"),
    )
    db.update_boundaries(highlight_id, body.start_pts, body.end_pts)
    db.update_status(highlight_id, "ADJUSTED")
    return {"id": highlight_id, "status": "ADJUSTED"}

@router.post("/api/highlights/{highlight_id}/llm-analyze")
def llm_analyze_highlight(highlight_id: int, db: Database = Depends(get_db)):
    """Editor-triggered LLM boundary refinement (Pass 1c)."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")

    boundary = BoundaryResult(
        trigger_pts=h["start_pts"],
        resolution_pts=h["end_pts"],
        peak_pts=h.get("peak_pts") or h["start_pts"],
        quality=h.get("quality") or "complete",
        context_status="FULL",
        stop_reason="editor_request",
    )

    if not _llm_gate.budget_tracker.can_call():
        raise HTTPException(status_code=503, detail="LLM daily budget exceeded")

    result = _llm_gate.refine_boundary(
        boundary,
        transcript=h.get("reason") or "",
        signals_summary={
            "peak_pts": h.get("peak_pts"),
            "peak_score": h.get("score"),
            "keywords": [],
        },
        force=True,
        gate="editor",
    )

    if result is None:
        raise HTTPException(status_code=503, detail="LLM analysis unavailable")

    return {
        "refined_start_pts": result.refined_start_pts,
        "refined_end_pts": result.refined_end_pts,
        "content_type": result.content_type,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }

@router.delete("/api/highlights/{highlight_id}")
def delete_highlight_endpoint(highlight_id: int, db: Database = Depends(get_db)):
    """Delete a rejected highlight and its video files."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    
    if h["status"] != "REJECTED":
        raise HTTPException(
            status_code=403,
            detail="Only rejected highlights can be deleted"
        )
    
    # Get file paths before DB deletion
    paths = db.delete_highlight(highlight_id)
    
    # Delete files from disk
    deleted_paths = []
    for path_key in ["clip_path", "draft_clip_path"]:
        path = paths.get(path_key)
        if path and os.path.exists(path):
            try:
                os.remove(path)
                deleted_paths.append(path)
            except OSError as e:
                logging.getLogger(__name__).warning(
                    "Failed to delete file %s: %s", path, e
                )
    
    return {
        "id": highlight_id,
        "status": "deleted",
        "deleted_paths": deleted_paths
    }

@router.get("/metrics")
def metrics():
    try:
        from src.observability.metrics import MetricsCollector

        text = MetricsCollector.get_instance().export_text()
    except ImportError:
        return Response(
            content="Metrics unavailable",
            status_code=503,
            media_type="text/plain",
        )
    return Response(content=text, media_type="text/plain")


@router.get("/api/health")
def health_liveness():
    return health_mod.check_liveness()


@router.get("/api/health/ready")
def health_readiness(
    db: Database = Depends(get_db),
    orch: OrchestratorService = Depends(get_orchestrator),
):
    db_ok = _check_db_ok(db)
    nodes = orch.get_node_health()
    result = health_mod.check_readiness(db_ok=db_ok, nodes=nodes)
    if not result["ready"]:
        return JSONResponse(status_code=503, content=result)
    return result


@router.get("/api/platforms")
def list_platforms(orch: OrchestratorService = Depends(get_orchestrator)):
    """Return registered platforms and availability."""
    return orch.list_platforms()


@router.get("/api/streams")
def list_streams(orch: OrchestratorService = Depends(get_orchestrator)):
    """Return metadata for all active stream workers."""
    return [
        {**stream, "running": stream.get("status") == "RUNNING"}
        for stream in orch.list_streams()
    ]


@router.get("/api/streams/interrupted")
def list_interrupted_streams(orch: OrchestratorService = Depends(get_orchestrator)):
    """Return streams marked INTERRUPTED after crash recovery."""
    return orch.list_interrupted()


@router.post("/api/streams/start")
def start_stream(
    body: StartStreamRequest,
    orch: OrchestratorService = Depends(get_orchestrator),
):
    """Start ingesting a new livestream."""
    try:
        orch.start_stream(body.url, body.stream_id, platform=body.platform)
    except CapacityError:
        raise HTTPException(status_code=429, detail="Maximum concurrent streams reached")
    except StreamAlreadyRunningError:
        raise HTTPException(status_code=409, detail="Stream already running")
    except PlatformNotSupportedError:
        raise HTTPException(status_code=501, detail="Platform not supported")
    return {"stream_id": body.stream_id, "status": "started"}


@router.post("/api/streams/{stream_id}/stop")
def stop_stream(
    stream_id: str,
    orch: OrchestratorService = Depends(get_orchestrator),
):
    """Stop an active stream worker."""
    try:
        orch.stop_stream(stream_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Stream not found")
    return {"stream_id": stream_id, "status": "stopped"}

# --- Application factory ---

def create_app() -> FastAPI:
    app = FastAPI(
        title="BaseLive Highlight Dashboard",
        description="Review and approve AI-detected livestream highlights.",
        version="1.0.0"
    )

    @app.middleware("http")
    async def log_requests(request, call_next):
        path = request.url.path
        if not path.startswith(("/static", "/clips")):
            logging.getLogger("src.api.access").info("%s %s", request.method, path)
        return await call_next(request)

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    clips_dir = "output/clips"
    os.makedirs(clips_dir, exist_ok=True)
    app.mount("/clips", StaticFiles(directory=clips_dir), name="clips")

    app.include_router(router)
    return app

app = create_app()
