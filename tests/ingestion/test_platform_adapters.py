from unittest.mock import MagicMock

import pytest

from src.ingestion.platforms import (
    FacebookAdapter,
    PlatformNotImplementedError,
    PlatformRegistry,
    TikTokAdapter,
    YouTubeAdapter,
    create_default_registry,
)


def test_registry_lists_platforms():
    reg = PlatformRegistry()
    reg.register(TikTokAdapter())
    reg.register(YouTubeAdapter())
    platforms = reg.list_platforms()
    ids = [p["id"] for p in platforms]
    assert "tiktok" in ids
    assert "youtube" in ids


def test_youtube_not_available():
    adapter = YouTubeAdapter()
    assert adapter.is_available() is False
    with pytest.raises(PlatformNotImplementedError):
        adapter.create_recorder("url", audio_buffer=MagicMock())


def test_facebook_not_available():
    adapter = FacebookAdapter()
    assert adapter.is_available() is False
    with pytest.raises(PlatformNotImplementedError):
        adapter.create_recorder("url", audio_buffer=MagicMock())
    with pytest.raises(PlatformNotImplementedError):
        adapter.create_chat_collector("url", chat_buffer=MagicMock())


def test_tiktok_extract_username():
    a = TikTokAdapter()
    assert a.extract_username("https://tiktok.com/@user/live") == "user"
    assert a.extract_username("user") == "user"


def test_tiktok_creates_recorder_and_collector():
    a = TikTokAdapter()
    recorder = a.create_recorder("http://x", audio_buffer=MagicMock())
    collector = a.create_chat_collector("http://x", chat_buffer=MagicMock())
    assert recorder is not None
    assert collector is not None


def test_create_default_registry():
    reg = create_default_registry()
    platforms = reg.list_platforms()
    ids = [p["id"] for p in platforms]
    assert ids == ["tiktok", "youtube", "facebook"]
    assert reg.get("tiktok").is_available() is True
    assert reg.get("youtube").is_available() is False
