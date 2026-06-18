from typing import Generator
from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os

from src.db.database import Database

# --- Dependency ---

def get_db() -> Generator:
    db = Database()
    db.init_db()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Schemas ---

class AdjustRequest(BaseModel):
    start_pts: float
    end_pts: float

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
def get_highlights(db: Database = Depends(get_db)):
    """Return all highlights ordered by newest first."""
    return db.get_highlights()

@router.post("/api/highlights/{highlight_id}/approve")
def approve_highlight(highlight_id: int, db: Database = Depends(get_db)):
    """Mark a highlight as APPROVED."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    db.update_status(highlight_id, "APPROVED")
    return {"id": highlight_id, "status": "APPROVED"}

@router.post("/api/highlights/{highlight_id}/reject")
def reject_highlight(highlight_id: int, db: Database = Depends(get_db)):
    """Mark a highlight as REJECTED."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    db.update_status(highlight_id, "REJECTED")
    return {"id": highlight_id, "status": "REJECTED"}

@router.post("/api/highlights/{highlight_id}/adjust")
def adjust_highlight(highlight_id: int, body: AdjustRequest, db: Database = Depends(get_db)):
    """Adjust the start/end timestamps of a highlight."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    db.update_boundaries(highlight_id, body.start_pts, body.end_pts)
    db.update_status(highlight_id, "ADJUSTED")
    return {"id": highlight_id, "status": "ADJUSTED"}

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
