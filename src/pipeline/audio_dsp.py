import numpy as np


class AudioAnalyzer:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.baseline_energy = 0.05
        self.baseline_pitch = 150.0
        self.silence_duration = 0.0

    def _frame_size(self) -> int:
        return int(self.sample_rate * 0.1)

    def _iter_frames(self, audio: np.ndarray):
        frame_size = self._frame_size()
        for start in range(0, len(audio) - frame_size + 1, frame_size):
            yield audio[start : start + frame_size]

    def _compute_rms(self, audio: np.ndarray) -> float:
        return float(np.sqrt(np.mean(audio**2)))

    def _pitch_from_frame(self, frame: np.ndarray) -> float:
        frame = frame - np.mean(frame)
        if np.std(frame) < 1e-6:
            return 0.0

        corr = np.correlate(frame, frame, mode="full")
        corr = corr[len(corr) // 2 :]
        corr = corr / (corr[0] + 1e-10)

        min_lag = int(self.sample_rate / 400)
        max_lag = min(int(self.sample_rate / 75), len(corr) - 1)
        if max_lag <= min_lag:
            return 0.0

        peak_lag = min_lag + int(np.argmax(corr[min_lag : max_lag + 1]))
        if corr[peak_lag] < 0.3:
            return 0.0

        return self.sample_rate / peak_lag

    def _estimate_pitch(self, audio: np.ndarray) -> float:
        frame_size = self._frame_size()
        if len(audio) < frame_size:
            return 0.0

        pitches = [
            p for frame in self._iter_frames(audio) if (p := self._pitch_from_frame(frame)) > 0
        ]
        if not pitches:
            return 0.0
        return float(np.median(pitches))

    def _pitch_deviation(self, audio: np.ndarray) -> float:
        current_pitch = self._estimate_pitch(audio)
        if current_pitch <= 0:
            return 0.0

        deviation = abs(current_pitch - self.baseline_pitch) / max(self.baseline_pitch, 1.0)
        self.baseline_pitch = 0.9 * self.baseline_pitch + 0.1 * current_pitch
        return float(min(1.0, deviation))

    def _frame_energies(self, audio: np.ndarray) -> np.ndarray:
        frame_size = self._frame_size()
        if len(audio) < frame_size:
            return np.array([self._compute_rms(audio)])

        return np.array([self._compute_rms(frame) for frame in self._iter_frames(audio)])

    def _detect_laughter(self, audio: np.ndarray) -> float:
        fft = np.fft.rfft(audio)
        freqs = np.fft.rfftfreq(len(audio), 1 / self.sample_rate)
        magnitude = np.abs(fft) ** 2

        total_energy = float(np.sum(magnitude)) + 1e-10
        hf_energy = float(np.sum(magnitude[freqs >= 400]))
        hf_ratio = hf_energy / total_energy

        energies = self._frame_energies(audio)
        if len(energies) < 2:
            burst_score = 0.0
        else:
            energies_norm = energies / (np.max(energies) + 1e-10)
            variance = float(np.var(energies_norm))

            env = energies - np.mean(energies)
            env_corr = np.correlate(env, env, mode="full")
            env_corr = env_corr[len(env_corr) // 2 :]
            env_corr = env_corr / (env_corr[0] + 1e-10)

            min_lag = max(1, int(0.1 / 0.1))
            max_lag = min(len(env_corr) - 1, len(energies) // 2)
            periodicity = (
                float(np.max(env_corr[min_lag : max_lag + 1]))
                if max_lag > min_lag
                else 0.0
            )
            burst_score = min(1.0, variance * 4.0 + periodicity * 0.5)

        return float(np.clip(hf_ratio * 0.6 + burst_score * 0.5, 0.0, 1.0))

    def _estimate_overlap(self, audio: np.ndarray) -> float:
        energies = self._frame_energies(audio)
        if len(energies) < 2:
            return 0.0
        return float(min(1.0, np.var(energies) * 50.0))

    def analyze_chunk(self, audio: np.ndarray, run_full_dsp: bool = True) -> dict:
        current_energy = self._compute_rms(audio)

        is_spike = current_energy > (self.baseline_energy * 3)
        self.baseline_energy = 0.9 * self.baseline_energy + 0.1 * current_energy

        if current_energy < 0.01:
            self.silence_duration += len(audio) / self.sample_rate
        else:
            self.silence_duration = 0.0

        score = min(1.0, current_energy / 1.0)

        pitch_deviation = self._pitch_deviation(audio) if run_full_dsp else 0.0
        laughter_prob = self._detect_laughter(audio) if run_full_dsp else 0.0

        return {
            "energy_score": score,
            "energy_spike": is_spike,
            "raw_rms": current_energy,
            "silence_before": self.silence_duration,
            "pitch_deviation": pitch_deviation,
            "laughter_prob": laughter_prob,
            "speaker_overlap": self._estimate_overlap(audio),
        }
