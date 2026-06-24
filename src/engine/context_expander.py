import re
from typing import Optional, Set

from src.buffer.circular_buffer import TranscriptBuffer
from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import BoundaryResult, EventCandidate, EventHistoryStore, TranscriptResult


def topic_jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def _tokenize(text: str) -> Set[str]:
    return {t.lower() for t in re.findall(r"\w+", text, re.UNICODE) if t}


class ContextExpander:
    MAX_LOOKBACK = 60.0
    MAX_LOOKFORWARD = 30.0
    STEP_SEC = 1.0
    NO_DATA_LOOKBACK_SEC = 30.0  # max lookback when signal buffer has no history

    TOPIC_THRESHOLD = 0.3
    LOW_SCORE_THRESHOLD = 0.15
    LOW_SCORE_DURATION = 5.0
    SILENCE_THRESHOLD = 3.0
    PEAK_MARGIN = 5.0
    KEYWORD_WINDOW_SEC = 10.0

    FORWARD_LOW_SCORE_THRESHOLD = 0.25
    FORWARD_LOW_SCORE_DURATION = 5.0
    FORWARD_LOW_SCORE_OFFSET = 2.0
    FORWARD_TOPIC_OFFSET = 1.0
    FORWARD_CHAT_BASELINE_RATIO = 1.5
    FORWARD_SILENCE_THRESHOLD = 5.0
    ENERGY_BASELINE = 0.05

    def look_back(
        self,
        peak_pts: float,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        event_history: EventHistoryStore,
    ) -> float:
        peak_keywords = self._extract_keywords(peak_pts, history, transcript)
        min_pts = peak_pts - self.MAX_LOOKBACK
        oldest = history.oldest_pts()
        has_history = history.get_at(oldest) is not None

        # Guard A: no signal history at all — don't scan 300s of nothing
        if not has_history:
            return max(min_pts, peak_pts - self.NO_DATA_LOOKBACK_SEC)

        low_score_run = 0.0
        last_high_pts: Optional[float] = None

        t = peak_pts
        while t > min_pts:
            t -= self.STEP_SEC

            if t <= min_pts:
                return min_pts

            if has_history and t < oldest:
                return oldest

            snapshot = history.get_at(t)

            if (
                snapshot
                and snapshot.silence_before > self.SILENCE_THRESHOLD
                and t < peak_pts - self.PEAK_MARGIN
            ):
                before_keywords = self._extract_keywords_range(
                    t - 5.0, t, history, transcript
                )
                if topic_jaccard(before_keywords, peak_keywords) >= self.TOPIC_THRESHOLD:
                    return t

            t_keywords = self._extract_keywords(t, history, transcript)
            if peak_keywords and t_keywords and topic_jaccard(t_keywords, peak_keywords) < self.TOPIC_THRESHOLD:
                return min(t + self.STEP_SEC, peak_pts)

            score = snapshot.composite_score if snapshot else 0.0
            if score < self.LOW_SCORE_THRESHOLD:
                if low_score_run == 0.0:
                    last_high_pts = t + self.STEP_SEC
                low_score_run += self.STEP_SEC
                if (
                    low_score_run >= self.LOW_SCORE_DURATION
                    and topic_jaccard(t_keywords, peak_keywords) < self.TOPIC_THRESHOLD
                    and last_high_pts is not None
                ):
                    return last_high_pts
                elif (
                    low_score_run >= self.LOW_SCORE_DURATION
                    and not peak_keywords
                    and last_high_pts is not None
                ):
                    return last_high_pts
            else:
                low_score_run = 0.0
                last_high_pts = None

            prior = event_history.contains_pts(t)
            if prior is not None:
                return prior.end_pts

        return min_pts

    def look_forward(
        self,
        peak_pts: float,
        close_pts: float,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        chat_volume_ratio: float = 0.0,
    ) -> float:
        peak_keywords = self._extract_keywords(peak_pts, history, transcript)
        max_pts = peak_pts + self.MAX_LOOKFORWARD
        chat_below_baseline = chat_volume_ratio < self.FORWARD_CHAT_BASELINE_RATIO

        low_score_run = 0.0
        t = close_pts

        while t <= max_pts:
            snapshot = history.get_at(t)

            score = snapshot.composite_score if snapshot else 0.0
            if score < self.FORWARD_LOW_SCORE_THRESHOLD:
                low_score_run += self.STEP_SEC
                if (
                    low_score_run >= self.FORWARD_LOW_SCORE_DURATION
                    and chat_below_baseline
                ):
                    return t - self.FORWARD_LOW_SCORE_OFFSET
            else:
                low_score_run = 0.0

            t_keywords = self._extract_keywords(t, history, transcript)
            if (
                peak_keywords
                and t_keywords
                and topic_jaccard(t_keywords, peak_keywords) < self.TOPIC_THRESHOLD
            ):
                return t - self.FORWARD_TOPIC_OFFSET

            if (
                snapshot
                and snapshot.silence_before > self.FORWARD_SILENCE_THRESHOLD
                and snapshot.audio_energy <= self.ENERGY_BASELINE
                and not snapshot.audio_energy_spike
            ):
                return t - snapshot.silence_before

            t += self.STEP_SEC

        return max_pts

    def expand(
        self,
        event: EventCandidate,
        resolution_pts: float,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        event_history: EventHistoryStore,
    ) -> BoundaryResult:
        peak_pts = event.peak_pts
        trigger_pts = self.look_back(peak_pts, history, transcript, event_history)

        quality = "complete"
        context_status = "FULL"
        stop_reason = "look_back_complete"

        min_pts = peak_pts - self.MAX_LOOKBACK
        oldest = history.oldest_pts()
        has_history = history.get_at(oldest) is not None

        if trigger_pts <= min_pts + self.STEP_SEC:
            quality = "possibly_incomplete"
            stop_reason = "max_lookback"

        if has_history and trigger_pts <= oldest + self.STEP_SEC:
            quality = "buffer_limited"
            context_status = "PARTIAL"
            stop_reason = "buffer_limited"

        if resolution_pts >= peak_pts + self.MAX_LOOKFORWARD - self.STEP_SEC:
            quality = "forced_close"
            stop_reason = "max_lookforward"

        return BoundaryResult(
            trigger_pts=trigger_pts,
            resolution_pts=resolution_pts,
            peak_pts=peak_pts,
            quality=quality,
            context_status=context_status,
            stop_reason=stop_reason,
        )

    def _extract_keywords(
        self,
        pts: float,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
    ) -> Set[str]:
        half = self.KEYWORD_WINDOW_SEC / 2
        return self._extract_keywords_range(pts - half, pts + half, history, transcript)

    def _extract_keywords_range(
        self,
        start_pts: float,
        end_pts: float,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
    ) -> Set[str]:
        keywords: Set[str] = set()
        for entry in history.get_range(start_pts, end_pts):
            keywords.update(entry.snapshot.keyword_triggered)
        for item in transcript.items:
            item_pts = item["pts"]
            if start_pts <= item_pts <= end_pts:
                result = item["item"]
                if isinstance(result, TranscriptResult):
                    keywords.update(_tokenize(result.text))
                elif isinstance(result, dict):
                    keywords.update(_tokenize(result.get("text", "")))
        return keywords
