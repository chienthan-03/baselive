"""YouTube platform adapter skeleton (not yet implemented)."""
from __future__ import annotations

from src.buffer.circular_buffer import AudioRingBuffer, ChatBuffer
from src.ingestion.platforms.base import (
    ChatCollectorProtocol,
    PlatformAdapter,
    PlatformNotImplementedError,
    RecorderProtocol,
)


class YouTubeAdapter(PlatformAdapter):
    platform_id = "youtube"
    default_chat_lag = 3.0

    def extract_username(self, url: str) -> str:
        return url.strip()

    def is_available(self) -> bool:
        return False

    def create_recorder(
        self, url: str, audio_buffer: AudioRingBuffer, **kwargs
    ) -> RecorderProtocol:
        raise PlatformNotImplementedError(
            f"{self.platform_id} recorder is not implemented"
        )

    def create_chat_collector(
        self, url: str, chat_buffer: ChatBuffer, **kwargs
    ) -> ChatCollectorProtocol:
        raise PlatformNotImplementedError(
            f"{self.platform_id} chat collector is not implemented"
        )
