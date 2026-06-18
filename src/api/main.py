from typing import Generator, Optional
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os

from src.core.models import BoundaryResult
from src.db.database import Database
from src.engine.llm_gate import LLMGate

# --- Dependency ---

def get_db() -> Generator:
    db = Database()
    db.init_db()
    try:
        yield db
    finally:
        db.close()

_llm_gate = LLMGate()

# --- Pydantic Schemas ---

class AdjustRequest(BaseModel):
    start_pts: float
    end_pts: float

class RejectRequest(BaseModel):
    reason: str

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

    result = _llm_gate.refine_boundary(
        boundary,
        transcript=h.get("reason") or "",
        signals_summary={
            "peak_pts": h.get("peak_pts"),
            "peak_score": h.get("score"),
            "keywords": [],
        },
        force=True,
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

# --- Application factory ---

def create_app() -> FastAPI:
    app = FastAPI(
        title="BaseLive Highlight Dashboard",
        description="Review and approve AI-detected livestream highlights.",
        version="1.0.0"
    )

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    clips_dir = "output/clips"
    os.makedirs(clips_dir, exist_ok=True)
    app.mount("/clips", StaticFiles(directory=clips_dir), name="clips")

    app.include_router(router)
    return app

app = create_app()
