from collections import deque
from typing import Dict

from src.core.models import SignalSnapshot

WEIGHTS: Dict[str, float] = {
    "energy": 0.25,
    "laughter": 0.20,
    "chat_volume": 0.15,
    "speaking_rate": 0.15,
    "pitch": 0.10,
    "emoji_dominant": 0.10,
    "overlap": 0.05,
}

STT_COMPONENTS = {"speaking_rate"}


class SignalAggregator:
    def __init__(
        self,
        window_size: int = 60,
        big_gift_threshold: float = 100,
        stt_enabled: bool = True,
    ):
        self.window_size = window_size
        self.big_gift_threshold = big_gift_threshold
        self.stt_enabled = stt_enabled
        self._history = {
            component: deque(maxlen=window_size) for component in WEIGHTS
        }

    def _normalize(self, component: str, value: float) -> float:
        history = self._history[component]
        history.append(value)
        if len(history) < 2:
            return max(0.0, min(1.0, value))
        min_val = min(history)
        max_val = max(history)
        if max_val == min_val:
            return 1.0 if value > 0 else 0.0
        return (value - min_val) / (max_val - min_val)

    def _emoji_dominant(self, snapshot: SignalSnapshot) -> float:
        if not snapshot.chat_emoji_scores:
            return 0.0
        return max(snapshot.chat_emoji_scores.values())

    def _energy_raw(self, snapshot: SignalSnapshot) -> float:
        if snapshot.audio_energy > 0:
            return snapshot.audio_energy
        return 1.0 if snapshot.audio_energy_spike else 0.0

    def _effective_weights(self) -> Dict[str, float]:
        weights = WEIGHTS.copy()
        if not self.stt_enabled:
            disabled_total = sum(weights[c] for c in STT_COMPONENTS)
            for component in STT_COMPONENTS:
                weights[component] = 0.0
            enabled_total = sum(weights.values())
            if enabled_total > 0:
                scale = (enabled_total + disabled_total) / enabled_total
                for component in weights:
                    if weights[component] > 0:
                        weights[component] *= scale
        return weights

    def compute_score(self, snapshot: SignalSnapshot) -> float:
        raw = {
            "energy": self._energy_raw(snapshot),
            "laughter": snapshot.laughter_prob,
            "chat_volume": snapshot.chat_volume_spike,
            "speaking_rate": snapshot.speaking_rate,
            "pitch": snapshot.pitch_deviation,
            "emoji_dominant": self._emoji_dominant(snapshot),
            "overlap": snapshot.speaker_overlap,
        }

        weights = self._effective_weights()
        score = sum(
            weights[component] * self._normalize(component, raw[component])
            for component in weights
            if weights[component] > 0
        )

        if snapshot.silence_before > 2.0 and snapshot.audio_energy_spike:
            score *= 1.5

        if self.stt_enabled and snapshot.keyword_triggered:
            score *= 1.3

        gift = snapshot.gift_event
        if gift and gift.get("value", 0) > self.big_gift_threshold:
            score *= 1.4

        snapshot.composite_score = score
        return score
