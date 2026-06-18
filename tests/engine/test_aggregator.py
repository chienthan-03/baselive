from src.engine.aggregator import SignalAggregator
from src.core.models import SignalSnapshot


def test_aggregator_excitement_formula():
    agg = SignalAggregator()
    snapshot = SignalSnapshot(
        pts=10.0,
        audio_energy_spike=True,
        laughter_prob=0.8,
        chat_volume_spike=1.0,
        speaking_rate=0.7,
        pitch_deviation=0.5,
        speaker_overlap=0.2,
        chat_emoji_scores={"funny": 0.9},
        silence_before=3.0,
        keyword_triggered=["ôi"],
    )
    score = agg.compute_score(snapshot)
    assert score > 0.6


def test_aggregator_stt_disabled_redistributes_weights():
    agg = SignalAggregator(stt_enabled=False)
    snapshot = SignalSnapshot(
        pts=10.0,
        audio_energy_spike=True,
        laughter_prob=0.8,
        chat_volume_spike=1.0,
        speaking_rate=0.0,
        pitch_deviation=0.5,
        speaker_overlap=0.2,
        chat_emoji_scores={"funny": 0.9},
    )
    score = agg.compute_score(snapshot)
    assert score > 0.0
    assert snapshot.composite_score == score
