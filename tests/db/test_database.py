import pytest
import sqlite3
from src.db.database import Database

@pytest.fixture
def test_db():
    # Sử dụng database in-memory cho testing để đảm bảo tốc độ và cách ly
    db = Database(db_path=":memory:")
    db.init_db()
    yield db
    db.close()

def test_database_initializes_tables(test_db):
    """Database init_db() should create the 'highlights' table."""
    cursor = test_db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='highlights'")
    assert cursor.fetchone() is not None

def test_insert_and_get_highlights(test_db):
    """Should correctly insert a highlight and retrieve it."""
    test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.85,
        clip_path="output/clips/test.mp4",
        status="PENDING",
        reason="high energy"
    )
    
    highlights = test_db.get_highlights()
    assert len(highlights) == 1
    h = highlights[0]
    assert h["stream_id"] == "test_stream"
    assert h["status"] == "PENDING"
    assert h["score"] == 0.85
    assert h["reason"] == "high energy"

def test_update_highlight_status(test_db):
    """Should correctly update the status of an existing highlight."""
    h_id = test_db.insert_highlight(
        stream_id="s1", start_pts=0.0, end_pts=5.0, score=0.9, clip_path="", status="PENDING"
    )
    
    test_db.update_status(h_id, "APPROVED")
    
    h = test_db.get_highlight(h_id)
    assert h is not None
    assert h["status"] == "APPROVED"

def test_update_highlight_boundaries(test_db):
    """Should correctly update start_pts and end_pts."""
    h_id = test_db.insert_highlight(
        stream_id="s1", start_pts=10.0, end_pts=20.0, score=0.9, clip_path="", status="PENDING"
    )
    
    test_db.update_boundaries(h_id, start_pts=5.0, end_pts=25.0)
    
    h = test_db.get_highlight(h_id)
    assert h["start_pts"] == 5.0
    assert h["end_pts"] == 25.0
