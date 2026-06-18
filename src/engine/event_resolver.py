import re
from dataclasses import replace
from typing import List, Tuple

from src.core.models import AmbiguousPair, ResolvedEvent, ResolutionResult
from src.engine.context_expander import topic_jaccard


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"\w+", text, re.UNICODE) if t}


class EventResolver:
    ADJACENT_GAP_SEC = 5.0
    TOPIC_MERGE_THRESHOLD = 0.7
    TOPIC_SEPARATE_THRESHOLD = 0.3
    SCORE_RATIO_SUBORDINATE = 3.0

    def resolve(self, events: List[ResolvedEvent]) -> ResolutionResult:
        if not events:
            return ResolutionResult(events=[], ambiguous_pairs=[])

        sorted_events = [self._clone(e) for e in sorted(events, key=lambda e: e.start_pts)]
        ambiguous_pairs: List[AmbiguousPair] = []
        resolved: List[ResolvedEvent] = []

        i = 0
        while i < len(sorted_events):
            current = sorted_events[i]
            j = i + 1

            while j < len(sorted_events):
                nxt = sorted_events[j]
                relation = self._classify_relation(current, nxt)

                if relation == "NONE":
                    break

                sim = self.topic_similarity(current, nxt)
                action = self._decide_action(relation, current, nxt, sim)

                if action == "AMBIGUOUS":
                    ambiguous_pairs.append(
                        AmbiguousPair(
                            event_a=self._clone(current),
                            event_b=self._clone(nxt),
                            similarity=sim,
                        )
                    )
                    break
                if action == "MERGE":
                    current = self._merge(current, nxt)
                    j += 1
                    continue
                if action == "SUBORDINATE":
                    current = self._subordinate(current, nxt)
                    j += 1
                    continue
                if action == "KEEP_BOTH_TRIM":
                    midpoint = (current.end_pts + nxt.start_pts) / 2
                    current = replace(current, end_pts=midpoint)
                    sorted_events[j] = replace(nxt, start_pts=midpoint)
                    break
                break

            resolved.append(current)
            i = j if j > i else i + 1

        return ResolutionResult(events=resolved, ambiguous_pairs=ambiguous_pairs)

    def topic_similarity(self, a: ResolvedEvent, b: ResolvedEvent) -> float:
        kw_a = {k.lower() for k in a.keywords}
        kw_b = {k.lower() for k in b.keywords}
        full_sim = topic_jaccard(
            kw_a | _tokenize(a.transcript_excerpt),
            kw_b | _tokenize(b.transcript_excerpt),
        )
        if kw_a and kw_b:
            return max(topic_jaccard(kw_a, kw_b), full_sim)
        return full_sim

    def _classify_relation(self, a: ResolvedEvent, b: ResolvedEvent) -> str:
        if a.end_pts <= b.start_pts:
            gap = b.start_pts - a.end_pts
            if gap < self.ADJACENT_GAP_SEC:
                return "ADJACENT"
            return "NONE"

        a_contains_b = a.start_pts <= b.start_pts and a.end_pts >= b.end_pts
        b_contains_a = b.start_pts <= a.start_pts and b.end_pts >= a.end_pts
        if a_contains_b or b_contains_a:
            return "NESTED"

        return "OVERLAP"

    def _decide_action(
        self,
        relation: str,
        a: ResolvedEvent,
        b: ResolvedEvent,
        sim: float,
    ) -> str:
        if relation == "OVERLAP":
            return self._decide_overlap(a, b, sim)
        if relation == "NESTED":
            return self._decide_nested(a, b, sim)
        if relation == "ADJACENT":
            return self._decide_adjacent(sim)
        return "KEEP_BOTH"

    def _decide_overlap(self, a: ResolvedEvent, b: ResolvedEvent, sim: float) -> str:
        if self._score_ratio(a, b) > self.SCORE_RATIO_SUBORDINATE:
            return "SUBORDINATE"
        if sim > self.TOPIC_MERGE_THRESHOLD:
            return "MERGE"
        if sim < self.TOPIC_SEPARATE_THRESHOLD:
            return "KEEP_BOTH_TRIM"
        return "AMBIGUOUS"

    def _decide_nested(self, a: ResolvedEvent, b: ResolvedEvent, sim: float) -> str:
        if sim > self.TOPIC_MERGE_THRESHOLD:
            return "SUBORDINATE"
        if sim < self.TOPIC_SEPARATE_THRESHOLD:
            return "KEEP_BOTH"
        return "AMBIGUOUS"

    def _decide_adjacent(self, sim: float) -> str:
        if sim > self.TOPIC_MERGE_THRESHOLD:
            return "MERGE"
        if sim < self.TOPIC_SEPARATE_THRESHOLD:
            return "KEEP_BOTH"
        return "AMBIGUOUS"

    def _score_ratio(self, a: ResolvedEvent, b: ResolvedEvent) -> float:
        high = max(a.peak_score, b.peak_score)
        low = min(a.peak_score, b.peak_score)
        if low <= 0:
            return float("inf") if high > 0 else 1.0
        return high / low

    def _merge(self, a: ResolvedEvent, b: ResolvedEvent) -> ResolvedEvent:
        dominant = a if a.peak_score >= b.peak_score else b
        subordinate = b if a.peak_score >= b.peak_score else a
        keywords = list(dict.fromkeys(a.keywords + b.keywords))
        sub_events = a.sub_events + b.sub_events
        if (
            subordinate.draft_highlight_id
            and subordinate.draft_highlight_id != dominant.draft_highlight_id
        ):
            sub_events = list(sub_events) + [self._clone(subordinate)]
        return ResolvedEvent(
            start_pts=min(a.start_pts, b.start_pts),
            end_pts=max(a.end_pts, b.end_pts),
            peak_pts=dominant.peak_pts,
            peak_score=dominant.peak_score,
            keywords=keywords,
            transcript_excerpt=f"{a.transcript_excerpt} {b.transcript_excerpt}".strip(),
            draft_highlight_id=dominant.draft_highlight_id or subordinate.draft_highlight_id,
            sub_events=sub_events,
        )

    def _subordinate(self, a: ResolvedEvent, b: ResolvedEvent) -> ResolvedEvent:
        if self._score_ratio(a, b) > self.SCORE_RATIO_SUBORDINATE:
            dominant, subordinate = (a, b) if a.peak_score >= b.peak_score else (b, a)
        else:
            dominant, subordinate = self._outer_inner(a, b)

        dominant = self._clone(dominant)
        subordinate = self._clone(subordinate)
        dominant.sub_events = list(dominant.sub_events) + [subordinate]
        return dominant

    def _outer_inner(
        self, a: ResolvedEvent, b: ResolvedEvent
    ) -> Tuple[ResolvedEvent, ResolvedEvent]:
        a_contains_b = a.start_pts <= b.start_pts and a.end_pts >= b.end_pts
        if a_contains_b:
            return a, b
        b_contains_a = b.start_pts <= a.start_pts and b.end_pts >= a.end_pts
        if b_contains_a:
            return b, a
        dominant = a if a.peak_score >= b.peak_score else b
        subordinate = b if a.peak_score >= b.peak_score else a
        return dominant, subordinate

    @staticmethod
    def _clone(event: ResolvedEvent) -> ResolvedEvent:
        return replace(event, sub_events=list(event.sub_events))
