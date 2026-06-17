import numpy as np
from typing import List, Dict, Any, Tuple

class AudioRingBuffer:
    def __init__(self, capacity_sec: int, sample_rate: int):
        self.capacity_samples = capacity_sec * sample_rate
        self.sample_rate = sample_rate
        self.buffer = np.zeros(self.capacity_samples, dtype=np.float32)
        self.write_pos = 0
        self.base_pts = 0.0

    def write(self, data: np.ndarray, start_pts: float):
        if self.write_pos == 0:
            self.base_pts = start_pts
        samples = len(data)
        if samples > self.capacity_samples:
            data = data[-self.capacity_samples:]
            samples = self.capacity_samples
        end_pos = self.write_pos + samples
        if end_pos <= self.capacity_samples:
            self.buffer[self.write_pos:end_pos] = data
        else:
            p1 = self.capacity_samples - self.write_pos
            p2 = samples - p1
            self.buffer[self.write_pos:] = data[:p1]
            self.buffer[:p2] = data[p1:]
        self.write_pos = end_pos % self.capacity_samples

    def read(self, start_pts: float, duration_sec: float) -> np.ndarray:
        start_sample = int((start_pts - self.base_pts) * self.sample_rate) % self.capacity_samples
        num_samples = int(duration_sec * self.sample_rate)
        end_sample = start_sample + num_samples
        if end_sample <= self.capacity_samples:
            return self.buffer[start_sample:end_sample].copy()
        else:
            p1 = self.capacity_samples - start_sample
            p2 = num_samples - p1
            return np.concatenate((self.buffer[start_sample:], self.buffer[:p2]))

class BaseListBuffer:
    def __init__(self, capacity_sec: int):
        self.capacity_sec = capacity_sec
        self.items: List[Dict[str, Any]] = []
        self.pinned_ranges: List[Tuple[float, float]] = []

    def pin_range(self, start_pts: float, end_pts: float):
        self.pinned_ranges.append((start_pts, end_pts))

    def _is_pinned(self, pts: float) -> bool:
        for (s, e) in self.pinned_ranges:
            if s <= pts <= e:
                return True
        return False

    def add_item(self, item: Any, pts: float):
        self.items.append({"item": item, "pts": pts})
        latest_pts = pts
        
        kept_items = []
        for i in self.items:
            if (latest_pts - i["pts"] <= self.capacity_sec) or self._is_pinned(i["pts"]):
                kept_items.append(i)
        self.items = kept_items

class VideoBuffer(BaseListBuffer):
    pass

class TranscriptBuffer(BaseListBuffer):
    pass

class ChatBuffer(BaseListBuffer):
    pass
