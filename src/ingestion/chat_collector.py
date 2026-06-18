"""
ChatCollector: Bridges the TikTok-Live-Connector Node.js script to Python.
Runs `node <bridge_path> <username>` as a subprocess, reads JSON events
line-by-line from stdout, and pushes them into a ChatBuffer.
"""
import subprocess
import threading
import logging
import json
import time
from typing import Optional

from src.buffer.circular_buffer import ChatBuffer

logger = logging.getLogger(__name__)

_DEFAULT_BRIDGE = "tools/tiktok_bridge/index.js"


class ChatCollector:
    """
    Starts the Node.js TikTok-Live-Connector bridge and feeds chat events
    into a ChatBuffer.

    Each line from Node bridge stdout must be a single JSON object:
        {"event_type": "COMMENT", "username": "...", "content": "...", "pts": 123.4, "gift_value": null}

    Usage:
        collector = ChatCollector(username="streamer123", chat_buffer=chat_buf)
        collector.start()
        ...
        collector.stop()
    """

    def __init__(
        self,
        username: str,
        chat_buffer: ChatBuffer,
        node_bridge_path: str = _DEFAULT_BRIDGE,
    ):
        self.username = username
        self.chat_buffer = chat_buffer
        self.node_bridge_path = node_bridge_path

        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the Node.js bridge subprocess and start the reader thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("ChatCollector already running")
            return

        self._stop_event.clear()
        self._launch_bridge()

        if self._proc is None:
            # Launch failed (e.g. Node.js not found) — stay stopped
            return

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("ChatCollector started for @%s", self.username)

    def stop(self) -> None:
        """Stop the reader thread and terminate the Node.js subprocess."""
        self._stop_event.set()
        if self._proc:
            self._proc.terminate()
            logger.info("ChatCollector stopped")

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch_bridge(self) -> None:
        """Start `node <bridge_path> <username>` subprocess."""
        try:
            self._proc = subprocess.Popen(
                ["node", self.node_bridge_path, self.username],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            logger.error("Could not launch Node.js bridge: %s. Chat signals disabled.", e)
            self._proc = None

    def _reader_loop(self) -> None:
        """Read JSON lines from bridge stdout until stopped or process ends."""
        while not self._stop_event.is_set():
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Node bridge process ended unexpectedly")
                break
            self._read_one_line()

    def _read_one_line(self) -> None:
        """Read one JSON line from the bridge stdout and push to ChatBuffer."""
        if self._proc is None or self._proc.stdout is None:
            return

        raw = self._proc.stdout.readline()
        if not raw:
            return

        try:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                return
            event = json.loads(line)
            pts = event.get("pts", time.time())
            self.chat_buffer.add_item(event, pts=pts)
            logger.debug("Chat event received: %s", event.get("event_type"))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse chat event JSON: %s | raw=%r", e, raw)
