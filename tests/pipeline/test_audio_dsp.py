import numpy as np
from src.pipeline.audio_dsp import AudioAnalyzer

def test_audio_dsp_basic():
    analyzer = AudioAnalyzer(sample_rate=16000)
    audio = np.random.normal(0, 0.1, 16000 * 5)
    
    res = analyzer.analyze_chunk(audio)
    assert 'energy_score' in res
    assert 'silence_before' in res


def test_audio_dsp_returns_extended_signals():
    analyzer = AudioAnalyzer(sample_rate=16000)
    audio = np.random.normal(0, 0.3, 16000 * 5)
    res = analyzer.analyze_chunk(audio)
    assert "pitch_deviation" in res
    assert "laughter_prob" in res
    assert "speaker_overlap" in res
    assert 0.0 <= res["laughter_prob"] <= 1.0


def test_laughter_detected_on_hf_burst():
    analyzer = AudioAnalyzer(sample_rate=16000)
    t = np.linspace(0, 5, 16000 * 5)
    burst = np.sin(2 * np.pi * 800 * t) * (np.sin(2 * np.pi * 4 * t) > 0)
    res = analyzer.analyze_chunk(burst.astype(np.float32))
    assert res["laughter_prob"] > 0.3
