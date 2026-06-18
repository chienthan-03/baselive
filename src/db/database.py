import sqlite3
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "base_live.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # Configure sqlite to return dictionary-like rows
        self.conn.row_factory = sqlite3.Row

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
        self.conn.commit()
        logger.info("Database initialized successfully.")

    def insert_highlight(self, stream_id: str, start_pts: float, end_pts: float, 
                         score: float, clip_path: str = "", status: str = "PENDING", 
                         reason: str = "") -> int:
        """Inserts a new highlight record and returns its ID."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO highlights (stream_id, start_pts, end_pts, score, clip_path, status, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (stream_id, start_pts, end_pts, score, clip_path, status, reason))
        self.conn.commit()
        return cursor.lastrowid

    def get_highlights(self) -> List[Dict]:
        """Retrieves all highlights, ordered by creation time descending."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM highlights ORDER BY created_at DESC")
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

    def close(self):
        """Closes the database connection."""
        self.conn.close()
