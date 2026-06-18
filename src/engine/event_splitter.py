from typing import List, Sequence, Tuple

from src.buffer.signal_history import HistoryEntry, SignalHistoryBuffer
from src.core.models import MicroHighlight, ResolvedEvent

MAX_SINGLE_HIGHLIGHT = 180.0
MIN_PROMINENCE = 0.3
MIN_PEAK_DISTANCE = 15.0
TIKTOK_TARGET = 45.0
TIKTOK_MAX = 60.0
TIKTOK_MIN = 15.0
MERGE_GAP = 5.0

TIKTOK_PRE_ROLL = 2.0
TIKTOK_POST_ROLL = 1.0


def _compute_prominence(scores: Sequence[float], peak_idx: int) -> float:
    peak_score = scores[peak_idx]
    left_min = peak_score
    for i in range(peak_idx - 1, -1, -1):
        left_min = min(left_min, scores[i])
        if scores[i] > peak_score:
            break
    right_min = peak_score
    for i in range(peak_idx + 1, len(scores)):
        right_min = min(right_min, scores[i])
        if scores[i] > peak_score:
            break
    return peak_score - max(left_min, right_min)


def find_local_maxima(
    entries: Sequence[HistoryEntry],
    min_prominence: float = MIN_PROMINENCE,
    min_distance: float = MIN_PEAK_DISTANCE,
) -> List[Tuple[int, float, float]]:
    if len(entries) < 3:
        return []

    scores = [e.snapshot.composite_score for e in entries]
    pts = [e.pts for e in entries]

    candidates: List[Tuple[int, float, float, float]] = []
    for i in range(1, len(scores) - 1):
        if scores[i] >= scores[i - 1] and scores[i] > scores[i + 1]:
            prominence = _compute_prominence(scores, i)
            if prominence >= min_prominence:
                candidates.append((i, pts[i], scores[i], prominence))

    candidates.sort(key=lambda item: -item[3])
    selected: List[Tuple[int, float, float, float]] = []
    for candidate in candidates:
        _, pt, _, _ = candidate
        if all(abs(pt - chosen[1]) >= min_distance for chosen in selected):
            selected.append(candidate)

    selected.sort(key=lambda item: item[1])
    return [(idx, pt, score) for idx, pt, score, _ in selected]


def _valley_between(
    entries: Sequence[HistoryEntry],
    left_idx: int,
    right_idx: int,
) -> float:
    if left_idx >= right_idx:
        return entries[left_idx].pts

    segment = entries[left_idx : right_idx + 1]
    valley_entry = min(segment, key=lambda e: e.snapshot.composite_score)
    return valley_entry.pts


class EventSplitter:
    def split(
        self,
        event: ResolvedEvent,
        history: SignalHistoryBuffer,
        platform: str = "tiktok",
    ) -> List[MicroHighlight]:
        duration = event.end_pts - event.start_pts
        if duration <= MAX_SINGLE_HIGHLIGHT:
            return [self._single_highlight(event, platform, split=False)]

        entries = history.get_range(event.start_pts, event.end_pts)
        if len(entries) < 3:
            return [self._single_highlight(event, platform, split=False)]

        peaks = find_local_maxima(entries)
        if len(peaks) < 2:
            return [self._single_highlight(event, platform, split=False)]

        highlights = self._highlights_from_peaks(event, entries, peaks, platform)
        highlights = self._merge_close(highlights)
        highlights = self._enforce_duration_limits(highlights, entries, platform)
        return highlights

    def _single_highlight(
        self,
        event: ResolvedEvent,
        platform: str,
        split: bool,
    ) -> MicroHighlight:
        pre_roll, post_roll = self._platform_rolls(platform, split)
        return MicroHighlight(
            start_pts=event.start_pts,
            end_pts=event.end_pts,
            peak_pts=event.peak_pts,
            peak_score=event.peak_score,
            parent_id=event.draft_highlight_id,
            pre_roll=pre_roll,
            post_roll=post_roll,
        )

    def _platform_rolls(
        self, platform: str, split: bool
    ) -> Tuple[float | None, float | None]:
        if not split or platform != "tiktok":
            return None, None
        return TIKTOK_PRE_ROLL, TIKTOK_POST_ROLL

    def _highlights_from_peaks(
        self,
        event: ResolvedEvent,
        entries: Sequence[HistoryEntry],
        peaks: List[Tuple[int, float, float]],
        platform: str,
    ) -> List[MicroHighlight]:
        pre_roll, post_roll = self._platform_rolls(platform, split=True)
        highlights: List[MicroHighlight] = []

        for i, (peak_idx, peak_pts, peak_score) in enumerate(peaks):
            if i == 0:
                start_pts = event.start_pts
            else:
                prev_idx = peaks[i - 1][0]
                start_pts = _valley_between(entries, prev_idx, peak_idx)

            if i == len(peaks) - 1:
                end_pts = event.end_pts
            else:
                next_idx = peaks[i + 1][0]
                end_pts = _valley_between(entries, peak_idx, next_idx)

            highlights.append(
                MicroHighlight(
                    start_pts=start_pts,
                    end_pts=end_pts,
                    peak_pts=peak_pts,
                    peak_score=peak_score,
                    parent_id=event.draft_highlight_id,
                    pre_roll=pre_roll,
                    post_roll=post_roll,
                )
            )

        return highlights

    def _merge_close(self, highlights: List[MicroHighlight]) -> List[MicroHighlight]:
        if not highlights:
            return []

        merged = [highlights[0]]
        for current in highlights[1:]:
            previous = merged[-1]
            gap = current.start_pts - previous.end_pts
            if gap < MERGE_GAP:
                keep_previous_peak = previous.peak_score >= current.peak_score
                merged[-1] = MicroHighlight(
                    start_pts=previous.start_pts,
                    end_pts=current.end_pts,
                    peak_pts=previous.peak_pts
                    if keep_previous_peak
                    else current.peak_pts,
                    peak_score=max(previous.peak_score, current.peak_score),
                    parent_id=previous.parent_id,
                    pre_roll=previous.pre_roll,
                    post_roll=previous.post_roll,
                )
            else:
                merged.append(current)
        return merged

    def _enforce_duration_limits(
        self,
        highlights: List[MicroHighlight],
        entries: Sequence[HistoryEntry],
        platform: str,
    ) -> List[MicroHighlight]:
        min_duration, max_duration = self._duration_bounds(platform)
        result: List[MicroHighlight] = []

        for highlight in highlights:
            duration = highlight.end_pts - highlight.start_pts
            if duration < min_duration:
                continue
            if duration > max_duration:
                result.extend(
                    self._resplit_or_trim(highlight, entries, platform)
                )
            else:
                result.append(highlight)

        return result

    def _duration_bounds(self, platform: str) -> Tuple[float, float]:
        if platform == "tiktok":
            return TIKTOK_MIN, TIKTOK_MAX
        return TIKTOK_MIN, TIKTOK_MAX

    def _resplit_or_trim(
        self,
        highlight: MicroHighlight,
        entries: Sequence[HistoryEntry],
        platform: str,
    ) -> List[MicroHighlight]:
        segment_entries = [
            e
            for e in entries
            if highlight.start_pts <= e.pts <= highlight.end_pts
        ]
        sub_peaks = find_local_maxima(segment_entries)
        if len(sub_peaks) >= 2:
            sub_highlights = self._highlights_from_peaks(
                ResolvedEvent(
                    start_pts=highlight.start_pts,
                    end_pts=highlight.end_pts,
                    peak_pts=highlight.peak_pts,
                    peak_score=highlight.peak_score,
                    keywords=[],
                    transcript_excerpt="",
                    draft_highlight_id=highlight.parent_id,
                ),
                segment_entries,
                sub_peaks,
                platform,
            )
            return self._enforce_duration_limits(
                sub_highlights, segment_entries, platform
            )

        _, max_duration = self._duration_bounds(platform)
        half = max_duration / 2.0
        start_pts = max(highlight.start_pts, highlight.peak_pts - half)
        end_pts = min(highlight.end_pts, highlight.peak_pts + half)
        if end_pts - start_pts > max_duration:
            end_pts = start_pts + max_duration
        if end_pts - start_pts < TIKTOK_MIN:
            return []

        return [
            MicroHighlight(
                start_pts=start_pts,
                end_pts=end_pts,
                peak_pts=highlight.peak_pts,
                peak_score=highlight.peak_score,
                parent_id=highlight.parent_id,
                pre_roll=highlight.pre_roll,
                post_roll=highlight.post_roll,
            )
        ]
