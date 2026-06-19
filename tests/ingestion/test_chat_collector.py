import pytest
import json
import threading
from unittest.mock import patch, MagicMock
from io import BytesIO, StringIO

from src.ingestion.chat_collector import ChatCollector
from src.buffer.circular_buffer import ChatBuffer


def _make_chat_buffer() -> ChatBuffer:
    return ChatBuffer(capacity_sec=600)


def test_chat_collector_parses_json_to_buffer():
    """ChatCollector should parse JSON lines from Node bridge and push to ChatBuffer."""
    messages = [
        {"event_type": "COMMENT", "username": "user1", "content": "haha", "pts": 100.0, "gift_value": None},
        {"event_type": "GIFT",    "username": "fan",   "content": "rose", "pts": 101.5, "gift_value": 5.0},
    ]
    fake_stdout_text = "\n".join(json.dumps(m) for m in messages) + "\n"
    fake_stdout = StringIO(fake_stdout_text)

    mock_proc = MagicMock()
    mock_proc.stdout = fake_stdout
    mock_proc.stderr = StringIO("") # Mock stderr
    mock_proc.poll.return_value = None

    chat_buffer = _make_chat_buffer()

    collector = ChatCollector(username="testuser", chat_buffer=chat_buffer)
    # Inject proc directly to avoid real Node.js call
    collector._proc = mock_proc

    # Read both messages
    collector._read_one_line()
    collector._read_one_line()

    items = [i["item"] for i in chat_buffer.items]
    assert len(items) == 2
    assert items[0]["content"] == "haha"
    assert items[1]["event_type"] == "GIFT"


def test_chat_collector_handles_node_not_found():
    """ChatCollector should set is_running=False gracefully if Node.js is missing."""
    chat_buffer = _make_chat_buffer()

    with patch("src.ingestion.chat_collector.subprocess.Popen", side_effect=FileNotFoundError("node not found")):
        collector = ChatCollector(username="testuser", chat_buffer=chat_buffer)
        collector.start()

    assert collector.is_running is False


def test_chat_collector_is_running_false_before_start():
    """ChatCollector should report is_running=False before start() is called."""
    chat_buffer = _make_chat_buffer()
    collector = ChatCollector(username="testuser", chat_buffer=chat_buffer)
    assert collector.is_running is False
