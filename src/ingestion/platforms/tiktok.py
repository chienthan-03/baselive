"""TikTok platform adapter wrapping StreamRecorder and ChatCollector."""
from __future__ import annotations

import re

from src.buffer.circular_buffer import AudioRingBuffer, ChatBuffer
from src.ingestion.chat_collector import ChatCollector
from src.ingestion.platforms.base import PlatformAdapter, RecorderProtocol
from src.ingestion.stream_recorder import StreamRecorder

_TIKTOK_USERNAME_RE = re.compile(
    r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#]+)|^@?([^/?#]+)$",
    re.IGNORECASE,
)


class TikTokAdapter(PlatformAdapter):
    platform_id = "tiktok"
    default_chat_lag = 5.0

    def extract_username(self, url: str) -> str:
        match = _TIKTOK_USERNAME_RE.search(url.strip())
        if match:
            return (match.group(1) or match.group(2)).lstrip("@")
        return url.strip().lstrip("@")

    def create_recorder(
        self, url: str, audio_buffer: AudioRingBuffer, **kwargs
    ) -> RecorderProtocol:
        return StreamRecorder(url=url, audio_buffer=audio_buffer, **kwargs)

    def create_chat_collector(
        self, url: str, chat_buffer: ChatBuffer, **kwargs
    ) -> ChatCollector:
        username = kwargs.pop("username", None) or self.extract_username(url)
        return ChatCollector(username=username, chat_buffer=chat_buffer, **kwargs)
