from src.pipeline.chat_analyzer import ChatAnalyzer
from src.pipeline.chat_lag import ChatLagCompensator


def test_adjust_message_applies_lag():
    comp = ChatLagCompensator(default_lag=5.0)
    msg = {"pts": 100.0, "content": "haha"}
    adjusted = comp.adjust_message(msg)
    assert adjusted["adjusted_pts"] == 95.0


def test_calibrate_updates_lag():
    comp = ChatLagCompensator(default_lag=5.0)
    comp.calibrate_from_spike(audio_spike_pts=100.0, chat_spike_pts=108.0)
    assert comp.current_lag > 5.0


def test_calibrate_rolling_average():
    comp = ChatLagCompensator(default_lag=5.0)
    comp.calibrate_from_spike(audio_spike_pts=100.0, chat_spike_pts=110.0)
    comp.calibrate_from_spike(audio_spike_pts=200.0, chat_spike_pts=214.0)
    assert comp.current_lag == 12.0


def test_chat_analyzer_uses_adjusted_pts():
    comp = ChatLagCompensator(default_lag=10.0)
    analyzer = ChatAnalyzer(lag_compensator=comp)
    messages = [
        {"msg": "haha", "pts": 50.0},
        {"msg": "game hay quá", "pts": 51.0},
    ]
    analyzer.analyze_batch(messages)
    assert messages[0]["adjusted_pts"] == 40.0
    assert messages[1]["adjusted_pts"] == 41.0


def test_chat_analyzer_spam_filter_uses_adjusted_pts():
    analyzer = ChatAnalyzer()
    messages = [
        {"content": "a", "username": "u1", "pts": 0.0, "adjusted_pts": 100.0},
        {"content": "b", "username": "u1", "pts": 20.0, "adjusted_pts": 101.0},
        {"content": "c", "username": "u1", "pts": 40.0, "adjusted_pts": 102.0},
        {"content": "d", "username": "u1", "pts": 60.0, "adjusted_pts": 103.0},
        {"content": "e", "username": "u1", "pts": 80.0, "adjusted_pts": 104.0},
        {"content": "f", "username": "u1", "pts": 100.0, "adjusted_pts": 105.0},
    ]
    result = analyzer.analyze_batch(messages)
    assert result["raw_volume"] < 6
