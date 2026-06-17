import numpy as np

class AudioAnalyzer:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.baseline_energy = 0.05
        self.silence_duration = 0.0
        
    def _compute_rms(self, audio: np.ndarray) -> float:
        return float(np.sqrt(np.mean(audio**2)))
        
    def analyze_chunk(self, audio: np.ndarray) -> dict:
        current_energy = self._compute_rms(audio)
        
        is_spike = current_energy > (self.baseline_energy * 3)
        self.baseline_energy = 0.9 * self.baseline_energy + 0.1 * current_energy
        
        if current_energy < 0.01:
            self.silence_duration += (len(audio) / self.sample_rate)
        else:
            self.silence_duration = 0.0
            
        score = min(1.0, current_energy / 1.0)
        
        return {
            "energy_score": score,
            "energy_spike": is_spike,
            "raw_rms": current_energy,
            "silence_before": self.silence_duration
        }
