import sqlite3
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_HIGHLIGHT_MIGRATIONS = [
    ("highlight_type", "TEXT DEFAULT 'FINAL'"),
    ("is_growing", "INTEGER DEFAULT 0"),
    ("quality", "TEXT DEFAULT 'complete'"),
    ("content_type", "TEXT"),
    ("draft_clip_path", "TEXT"),
    ("parent_id", "INTEGER"),
    ("peak_pts", "REAL"),
    ("ai_start_pts", "REAL"),
    ("ai_end_pts", "REAL"),
]


class Database:
    def __init__(self, db_path: str = "base_live.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # Configure sqlite to return dictionary-like rows
        self.conn.row_factory = sqlite3.Row

    def _migrate_highlights_columns(self, cursor):
        cursor.execute("PRAGMA table_info(highlights)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _HIGHLIGHT_MIGRATIONS:
            if col_name not in existing:
                cursor.execute(f"ALTER TABLE highlights ADD COLUMN {col_name} {col_def}")

    def init_db(self):
        """Creates the necessary tables if they don't exist."""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id TEXT NOT NULL,
                start_pts REAL NOT NULL,
                end_pts REAL NOT NULL,
                score REAL NOT NULL,
                clip_path TEXT,
                status TEXT DEFAULT 'PENDING',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self._migrate_highlights_columns(cursor)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS highlight_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                highlight_id INTEGER NOT NULL,
                stream_id TEXT NOT NULL,
                editor_id TEXT DEFAULT 'default',
                ai_start_pts REAL,
                ai_end_pts REAL,
                ai_score REAL,
                action TEXT NOT NULL,
                editor_start_pts REAL,
                editor_end_pts REAL,
                reject_reason TEXT,
                start_delta_sec REAL,
                end_delta_sec REAL,
                content_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streams (
                stream_id TEXT PRIMARY KEY,
                platform TEXT,
                url TEXT,
                status TEXT,
                node_id TEXT,
                started_at REAL,
                ended_at REAL
            )
        ''')
        self.conn.commit()
        logger.info("Database initialized successfully.")

    def insert_highlight(
        self,
        stream_id: str,
        start_pts: float,
        end_pts: float,
        score: float,
        clip_path: str = "",
        status: str = "PENDING",
        reason: str = "",
        highlight_type: str = "FINAL",
        is_growing: int = 0,
        quality: str = "complete",
        content_type: Optional[str] = None,
        draft_clip_path: Optional[str] = None,
        parent_id: Optional[int] = None,
        peak_pts: Optional[float] = None,
        ai_start_pts: Optional[float] = None,
        ai_end_pts: Optional[float] = None,
    ) -> int:
        """Inserts a new highlight record and returns its ID."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO highlights (
                stream_id, start_pts, end_pts, score, clip_path, status, reason,
                highlight_type, is_growing, quality, content_type, draft_clip_path,
                parent_id, peak_pts, ai_start_pts, ai_end_pts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            stream_id, start_pts, end_pts, score, clip_path, status, reason,
            highlight_type, is_growing, quality, content_type, draft_clip_path,
            parent_id, peak_pts, ai_start_pts, ai_end_pts,
        ))
        self.conn.commit()
        return cursor.lastrowid

    def get_highlights(
        self,
        type: Optional[str] = None,
        stream_id: Optional[str] = None,
    ) -> List[Dict]:
        """Retrieves highlights, ordered by creation time descending."""
        conditions = ["status != 'MERGED'"]
        params: list = []
        if type is not None:
            conditions.append("highlight_type = ?")
            params.append(type)
        if stream_id is not None:
            conditions.append("stream_id = ?")
            params.append(stream_id)
        where = "WHERE " + " AND ".join(conditions)
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT * FROM highlights {where} ORDER BY created_at DESC",
            params,
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_highlight(self, highlight_id: int) -> Optional[Dict]:
        """Retrieves a single highlight by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM highlights WHERE id = ?", (highlight_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_status(self, highlight_id: int, new_status: str):
        """Updates the status of a highlight (e.g., PENDING -> APPROVED)."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE highlights SET status = ? WHERE id = ?", (new_status, highlight_id))
        self.conn.commit()

    def update_boundaries(self, highlight_id: int, start_pts: float, end_pts: float):
        """Updates the pre-roll/post-roll boundaries of a highlight."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE highlights SET start_pts = ?, end_pts = ? WHERE id = ?",
                       (start_pts, end_pts, highlight_id))
        self.conn.commit()

    def update_highlight(self, highlight_id: int, **fields):
        """Updates arbitrary allowed fields on a highlight."""
        allowed = {
            "stream_id", "start_pts", "end_pts", "score", "clip_path", "status", "reason",
            "highlight_type", "is_growing", "quality", "content_type", "draft_clip_path",
            "parent_id", "peak_pts", "ai_start_pts", "ai_end_pts",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [highlight_id]
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE highlights SET {set_clause} WHERE id = ?", values)
        self.conn.commit()

    def upgrade_to_final(
        self,
        highlight_id: int,
        start_pts: float,
        end_pts: float,
        clip_path: str,
        quality: str = "complete",
        content_type: Optional[str] = None,
        ai_start_pts: Optional[float] = None,
        ai_end_pts: Optional[float] = None,
    ):
        """Upgrade a DRAFT highlight to FINAL with refined boundaries."""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE highlights SET
                highlight_type = 'FINAL',
                is_growing = 0,
                start_pts = ?,
                end_pts = ?,
                clip_path = ?,
                quality = ?,
                content_type = ?,
                ai_start_pts = ?,
                ai_end_pts = ?
            WHERE id = ?
        ''', (start_pts, end_pts, clip_path, quality, content_type,
              ai_start_pts, ai_end_pts, highlight_id))
        self.conn.commit()

    def insert_feedback(
        self,
        highlight_id: int,
        stream_id: str,
        action: str,
        *,
        editor_id: str = "default",
        ai_start_pts: Optional[float] = None,
        ai_end_pts: Optional[float] = None,
        ai_score: Optional[float] = None,
        editor_start_pts: Optional[float] = None,
        editor_end_pts: Optional[float] = None,
        reject_reason: Optional[str] = None,
        start_delta_sec: Optional[float] = None,
        end_delta_sec: Optional[float] = None,
        content_type: Optional[str] = None,
    ) -> int:
        """Inserts editor feedback for a highlight and returns its ID."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO highlight_feedback (
                highlight_id, stream_id, editor_id, ai_start_pts, ai_end_pts,
                ai_score, action, editor_start_pts, editor_end_pts, reject_reason,
                start_delta_sec, end_delta_sec, content_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            highlight_id, stream_id, editor_id, ai_start_pts, ai_end_pts,
            ai_score, action, editor_start_pts, editor_end_pts, reject_reason,
            start_delta_sec, end_delta_sec, content_type,
        ))
        self.conn.commit()
        return cursor.lastrowid

    def get_feedback_for_highlight(self, highlight_id: int) -> List[Dict]:
        """Retrieves all feedback entries for a highlight, newest first."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM highlight_feedback WHERE highlight_id = ? ORDER BY created_at DESC",
            (highlight_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_feedback_since(self, hours: int = 24) -> List[Dict]:
        """Retrieves feedback entries from the last N hours for the learner."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM highlight_feedback WHERE created_at >= datetime('now', ?) ORDER BY created_at DESC",
            (f"-{hours} hours",),
        )
        return [dict(row) for row in cursor.fetchall()]

    def upsert_stream(
        self,
        stream_id: str,
        *,
        platform: str,
        url: str,
        status: str,
        node_id: str,
        started_at: float,
        ended_at: Optional[float] = None,
    ):
        """Insert or replace a stream record."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO streams (stream_id, platform, url, status, node_id, started_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stream_id) DO UPDATE SET
                platform = excluded.platform,
                url = excluded.url,
                status = excluded.status,
                node_id = excluded.node_id,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at
        ''', (stream_id, platform, url, status, node_id, started_at, ended_at))
        self.conn.commit()

    def get_stream(self, stream_id: str) -> Optional[Dict]:
        """Retrieves a single stream by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM streams WHERE stream_id = ?", (stream_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_stream_status(
        self,
        stream_id: str,
        status: str,
        *,
        ended_at: Optional[float] = None,
    ):
        """Updates the status (and optionally ended_at) of a stream."""
        cursor = self.conn.cursor()
        if ended_at is not None:
            cursor.execute(
                "UPDATE streams SET status = ?, ended_at = ? WHERE stream_id = ?",
                (status, ended_at, stream_id),
            )
        else:
            cursor.execute(
                "UPDATE streams SET status = ? WHERE stream_id = ?",
                (status, stream_id),
            )
        self.conn.commit()

    def list_streams_by_status(self, status: str) -> List[Dict]:
        """Retrieves all streams with the given status."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM streams WHERE status = ? ORDER BY started_at DESC",
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Closes the database connection."""
        self.conn.close()
