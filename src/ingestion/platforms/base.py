"""Platform adapter ABC, protocols, and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Protocol

from src.buffer.circular_buffer import AudioRingBuffer, ChatBuffer


class PlatformNotImplementedError(Exception):
    """Raised when a skeleton adapter is invoked."""


class RecorderProtocol(Protocol):
    is_running: bool
    video_path: str

    def start(self) -> None: ...

    def stop(self) -> None: ...


class ChatCollectorProtocol(Protocol):
    is_running: bool

    def start(self) -> None: ...

    def stop(self) -> None: ...


class PlatformAdapter(ABC):
    platform_id: str
    default_chat_lag: float

    @abstractmethod
    def extract_username(self, url: str) -> str: ...

    @abstractmethod
    def create_recorder(
        self, url: str, audio_buffer: AudioRingBuffer, **kwargs
    ) -> RecorderProtocol: ...

    @abstractmethod
    def create_chat_collector(
        self, url: str, chat_buffer: ChatBuffer, **kwargs
    ) -> ChatCollectorProtocol: ...

    def is_available(self) -> bool:
        return True


class PlatformRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.platform_id] = adapter

    def get(self, platform_id: str) -> PlatformAdapter:
        try:
            return self._adapters[platform_id]
        except KeyError as exc:
            raise KeyError(f"Unknown platform: {platform_id!r}") from exc

    def list_platforms(self) -> List[dict]:
        return [
            {
                "id": adapter.platform_id,
                "available": adapter.is_available(),
                "default_chat_lag": adapter.default_chat_lag,
            }
            for adapter in self._adapters.values()
        ]


def create_default_registry() -> PlatformRegistry:
    from src.ingestion.platforms.facebook import FacebookAdapter
    from src.ingestion.platforms.tiktok import TikTokAdapter
    from src.ingestion.platforms.youtube import YouTubeAdapter

    registry = PlatformRegistry()
    registry.register(TikTokAdapter())
    registry.register(YouTubeAdapter())
    registry.register(FacebookAdapter())
    return registry
