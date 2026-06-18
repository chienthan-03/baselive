import pytest
from src.pipeline.chat_analyzer import ChatAnalyzer


def test_chat_analysis():
    analyzer = ChatAnalyzer()
    messages = [
        {"msg": "haha", "pts": 1.0},
        {"msg": "game hay quá", "pts": 1.1},
        {"msg": "bình thường", "pts": 1.2},
    ]

    result = analyzer.analyze_batch(messages)
    assert result["chat_volume_spike"] > 0
    assert "haha" in result["keyword_triggered"]


def test_chat_analyzer_emoji_categories():
    analyzer = ChatAnalyzer()
    messages = [
        {"content": "😂😂😂", "event_type": "COMMENT"},
        {"content": "haha", "event_type": "COMMENT"},
    ]
    result = analyzer.analyze_batch(messages)
    assert result["chat_emoji_scores"]["funny"] > 0


def test_chat_analyzer_gift_detection():
    analyzer = ChatAnalyzer()
    messages = [{"event_type": "GIFT", "content": "sent rose", "gift_value": 500}]
    result = analyzer.analyze_batch(messages)
    assert result["gift_event"] is not None
    assert result["gift_event"]["value"] == 500


def test_chat_analyzer_spam_filter():
    analyzer = ChatAnalyzer()
    messages = [{"content": "spam", "username": "bot"}] * 5
    result = analyzer.analyze_batch(messages)
    assert result["raw_volume"] == 0
