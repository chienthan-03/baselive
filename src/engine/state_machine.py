from typing import Optional

from src.core.models import EventCandidate, SignalSnapshot, ThresholdSet


class StateMachine:
    OPEN_THR = 0.5
    CONFIRM_THR = 0.65
    CLOSE_THR = 0.25
    CLOSE_COOLDOWN = 5.0
    MAX_EVENT_DURATION = 600
    CHAT_CLOSE_RATIO = 1.5
    OPENING_TIMEOUT = 8.0

    def __init__(self):
        self.current_event = EventCandidate()

    def process(
        self,
        snapshot: SignalSnapshot,
        chat_volume_ratio: Optional[float] = None,
        thresholds: Optional[ThresholdSet] = None,
    ):
        self.current_event.signals.append(snapshot)

        score = snapshot.composite_score
        pts = snapshot.pts
        ev = self.current_event
        open_thr = thresholds.open_thr if thresholds else self.OPEN_THR
        confirm_thr = thresholds.confirm_thr if thresholds else self.CONFIRM_THR
        close_thr = thresholds.close_thr if thresholds else self.CLOSE_THR

        if ev.state == "IDLE":
            if score > open_thr:
                ev.state = "OPENING"
                ev.start_pts = pts

        elif ev.state == "OPENING":
            if score > confirm_thr:
                ev.state = "ACTIVE"
                ev.peak_score = score
                ev.peak_pts = pts
            elif pts - ev.start_pts > self.OPENING_TIMEOUT:
                ev.state = "IDLE"

        elif ev.state == "ACTIVE":
            if score > ev.peak_score:
                ev.peak_score = score
                ev.peak_pts = pts

            if pts - ev.start_pts > self.MAX_EVENT_DURATION:
                ev.state = "CLOSED"
                ev.end_pts = pts
                return

            if score < close_thr:
                if ev.below_close_since == 0.0:
                    ev.below_close_since = pts
                elif pts - ev.below_close_since >= self.CLOSE_COOLDOWN:
                    ratio = chat_volume_ratio if chat_volume_ratio is not None else 0.0
                    if ratio < self.CHAT_CLOSE_RATIO:
                        ev.state = "CLOSED"
                        ev.end_pts = ev.below_close_since
            else:
                ev.below_close_since = 0.0
