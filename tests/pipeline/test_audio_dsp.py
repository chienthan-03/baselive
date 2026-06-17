import numpy as np
from src.pipeline.audio_dsp import AudioAnalyzer

def test_audio_dsp_basic():
    analyzer = AudioAnalyzer(sample_rate=16000)
    audio = np.random.normal(0, 0.1, 16000 * 5)
    
    res = analyzer.analyze_chunk(audio)
    assert 'energy_score' in res
    assert 'silence_before' in res
