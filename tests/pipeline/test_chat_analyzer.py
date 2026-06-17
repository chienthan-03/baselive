import pytest
from src.pipeline.chat_analyzer import ChatAnalyzer

def test_chat_analysis():
    analyzer = ChatAnalyzer()
    messages = [
        {"msg": "haha", "pts": 1.0},
        {"msg": "game hay quá", "pts": 1.1},
        {"msg": "bình thường", "pts": 1.2}
    ]
    
    result = analyzer.analyze_batch(messages)
    assert result["chat_volume_spike"] > 0
    assert "haha" in result["keyword_triggered"]
