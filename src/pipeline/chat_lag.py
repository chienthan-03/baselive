from typing import List


class ChatLagCompensator:
    DEFAULT_LAG_TIKTOK = 5.0
    MAX_SPIKE_HISTORY = 10

    def __init__(self, default_lag: float = 5.0):
        self._current_lag = default_lag
        self._spike_pairs: List[float] = []

    @property
    def current_lag(self) -> float:
        return self._current_lag

    def adjust_message(self, msg: dict) -> dict:
        msg["adjusted_pts"] = msg.get("pts", 0) - self._current_lag
        return msg

    def calibrate_from_spike(self, audio_spike_pts: float, chat_spike_pts: float) -> None:
        lag = chat_spike_pts - audio_spike_pts
        self._spike_pairs.append(lag)
        if len(self._spike_pairs) > self.MAX_SPIKE_HISTORY:
            self._spike_pairs = self._spike_pairs[-self.MAX_SPIKE_HISTORY :]
        self._current_lag = sum(self._spike_pairs) / len(self._spike_pairs)
