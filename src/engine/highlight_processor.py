from dataclasses import replace
from typing import Dict, List, Optional

from src.buffer.circular_buffer import TranscriptBuffer
from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import (
    AmbiguousPair,
    BoundaryResult,
    EventCandidate,
    EventHistoryStore,
    MicroHighlight,
    ResolvedEvent,
)
from src.engine.clip_generator import ClipGenerator
from src.engine.context_expander import ContextExpander
from src.engine.event_resolver import EventResolver
from src.engine.event_splitter import EventSplitter
from src.engine.llm_gate import LLMGate
from src.engine.pending_event_queue import PendingEventQueue
from src.engine.state_machine import StateMachine
from src.db.database import Database


class HighlightProcessor:
    def __init__(
        self,
        context_expander: ContextExpander,
        clip_generator: Optional[ClipGenerator] = None,
        db: Optional[Database] = None,
        state_machine: Optional[StateMachine] = None,
        llm_gate: Optional[LLMGate] = None,
        event_resolver: Optional[EventResolver] = None,
        event_splitter: Optional[EventSplitter] = None,
        stream_id: str = "default",
        metrics=None,
    ):
        self.context_expander = context_expander
        self.clip_generator = clip_generator
        self.db = db
        self.state_machine = state_machine
        self.llm_gate = llm_gate or LLMGate()
        self.event_resolver = event_resolver or EventResolver()
        self.event_splitter = event_splitter or EventSplitter()
        self.stream_id = stream_id
        self._metrics = metrics
        self.event_history = EventHistoryStore()
        self.pending_queue = PendingEventQueue()

    def record_highlight_created(self, highlight_type: str) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.inc_highlight(highlight_type)
        except Exception:
            pass

    def on_event_closed(
        self,
        event: EventCandidate,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        clip_source: str,
        resolution_pts: float,
        current_pts: float,
    ) -> None:
        boundary = self.context_expander.expand(
            event,
            resolution_pts,
            history,
            transcript,
            self.event_history,
        )
        resolved = self.to_resolved(boundary, event)
        self.pending_queue.enqueue(resolved, current_pts)

        if self.pending_queue.is_ready(current_pts):
            self.process_pending_queue(history, transcript, clip_source)

        if self.state_machine is not None:
            self.state_machine.current_event = EventCandidate()

    def process_pending_queue(
        self,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        clip_source: str,
    ) -> List[Dict]:
        events = self.pending_queue.drain()
        if not events:
            return []

        if clip_source and self.clip_generator is not None:
            self.clip_generator.source_file = clip_source

        for index, resolved in enumerate(events):
            events[index] = self._maybe_refine_boundary(resolved)

        resolution = self.event_resolver.resolve(events)
        events = self._apply_overlap_decisions(
            resolution.events, resolution.ambiguous_pairs
        )

        results: List[Dict] = []
        for resolved in events:
            results.extend(self._finalize_event(resolved, history))

        return results

    def _maybe_refine_boundary(self, resolved: ResolvedEvent) -> ResolvedEvent:
        boundary = BoundaryResult(
            trigger_pts=resolved.start_pts,
            resolution_pts=resolved.end_pts,
            peak_pts=resolved.peak_pts,
            quality="complete",
            context_status="FULL",
            stop_reason="pending_queue",
        )
        event_stub = EventCandidate(
            peak_pts=resolved.peak_pts,
            peak_score=resolved.peak_score,
            draft_highlight_id=resolved.draft_highlight_id,
        )

        if not self.llm_gate.should_refine_boundary(event_stub, boundary):
            return resolved

        refine_result = self.llm_gate.refine_boundary(
            boundary,
            transcript=resolved.transcript_excerpt,
            signals_summary={},
        )
        if refine_result is None:
            return resolved

        return replace(
            resolved,
            start_pts=refine_result.refined_start_pts,
            end_pts=refine_result.refined_end_pts,
        )

    def _apply_overlap_decisions(
        self,
        events: List[ResolvedEvent],
        ambiguous_pairs: List[AmbiguousPair],
    ) -> List[ResolvedEvent]:
        if not ambiguous_pairs:
            return events

        result = list(events)
        for pair in ambiguous_pairs:
            overlap_result = self.llm_gate.resolve_overlap(pair)
            if overlap_result is None:
                continue

            idx_a = self._find_event_index(result, pair.event_a)
            idx_b = self._find_event_index(result, pair.event_b)
            if idx_a is None or idx_b is None:
                continue

            if idx_a > idx_b:
                idx_a, idx_b = idx_b, idx_a

            event_a = result[idx_a]
            event_b = result[idx_b]
            decision = overlap_result.decision

            if decision == "MERGE":
                merged = self.event_resolver._merge(event_a, event_b)
                result = result[:idx_a] + [merged] + result[idx_b + 1 :]
            elif decision == "KEEP_BOTH":
                midpoint = (event_a.end_pts + event_b.start_pts) / 2
                result[idx_a] = replace(event_a, end_pts=midpoint)
                result[idx_b] = replace(event_b, start_pts=midpoint)
            elif decision == "SUBORDINATE":
                subordinated = self.event_resolver._subordinate(event_a, event_b)
                result = result[:idx_a] + [subordinated] + result[idx_b + 1 :]

        return result

    @staticmethod
    def _find_event_index(
        events: List[ResolvedEvent], target: ResolvedEvent
    ) -> Optional[int]:
        for index, event in enumerate(events):
            if (
                event.start_pts == target.start_pts
                and event.end_pts == target.end_pts
                and event.peak_pts == target.peak_pts
                and event.draft_highlight_id == target.draft_highlight_id
            ):
                return index
        return None

    def _finalize_event(
        self,
        resolved: ResolvedEvent,
        history: SignalHistoryBuffer,
    ) -> List[Dict]:
        splits = self.event_splitter.split(resolved, history)
        if len(splits) <= 1:
            return [self._finalize_single(resolved, splits[0])]

        return self._finalize_split(resolved, splits)

    def _finalize_single(
        self,
        resolved: ResolvedEvent,
        micro: MicroHighlight,
    ) -> Dict:
        clip_path = self._generate_clip(micro, resolved)
        record = self._upgrade_draft_to_final(resolved, micro, clip_path)
        self.event_history.append(resolved)
        return record

    def _finalize_split(
        self,
        resolved: ResolvedEvent,
        splits: List[MicroHighlight],
    ) -> List[Dict]:
        parent_id = resolved.draft_highlight_id
        records: List[Dict] = []

        if parent_id is not None and self.db is not None:
            self.db.upgrade_to_final(
                parent_id,
                start_pts=resolved.start_pts,
                end_pts=resolved.end_pts,
                clip_path="",
                quality="complete",
            )
            self.record_highlight_created("FINAL")
            parent_record = self.db.get_highlight(parent_id)
            if parent_record is not None:
                records.append(parent_record)

        for micro in splits:
            clip_path = self._generate_clip(micro, resolved)
            if self.db is not None:
                child_id = self.db.insert_highlight(
                    stream_id=self.stream_id,
                    start_pts=micro.start_pts,
                    end_pts=micro.end_pts,
                    score=micro.peak_score,
                    clip_path=clip_path,
                    status="PENDING",
                    highlight_type="FINAL",
                    parent_id=parent_id,
                    peak_pts=micro.peak_pts,
                )
                child_record = self.db.get_highlight(child_id)
                if child_record is not None:
                    records.append(child_record)
                    self.record_highlight_created("FINAL")

        self._mark_merged_drafts(resolved)
        self.event_history.append(resolved)
        return records

    def _mark_merged_drafts(self, resolved: ResolvedEvent) -> None:
        if self.db is None:
            return

        kept_id = resolved.draft_highlight_id
        for sub_event in resolved.sub_events:
            draft_id = sub_event.draft_highlight_id
            if draft_id is not None and draft_id != kept_id:
                self.db.update_status(draft_id, "MERGED")

    def _upgrade_draft_to_final(
        self,
        resolved: ResolvedEvent,
        micro: MicroHighlight,
        clip_path: str,
    ) -> Dict:
        if self.db is not None and resolved.draft_highlight_id is not None:
            self.db.upgrade_to_final(
                resolved.draft_highlight_id,
                start_pts=micro.start_pts,
                end_pts=micro.end_pts,
                clip_path=clip_path,
                quality="complete",
            )
            self._mark_merged_drafts(resolved)
            record = self.db.get_highlight(resolved.draft_highlight_id)
            if record is not None:
                self.record_highlight_created("FINAL")
                return record

        return {
            "highlight_type": "FINAL",
            "start_pts": micro.start_pts,
            "end_pts": micro.end_pts,
            "clip_path": clip_path,
            "peak_pts": micro.peak_pts,
            "score": micro.peak_score,
        }

    def _generate_clip(
        self,
        micro: MicroHighlight,
        resolved: ResolvedEvent,
    ) -> str:
        if self.clip_generator is None:
            return ""

        event_stub = EventCandidate(
            peak_pts=micro.peak_pts,
            peak_score=micro.peak_score,
            draft_highlight_id=resolved.draft_highlight_id,
        )
        return self.clip_generator.generate_final(
            micro.start_pts,
            micro.end_pts,
            event_stub,
            pre_roll=micro.pre_roll,
            post_roll=micro.post_roll,
        )

    def to_resolved(
        self, boundary: BoundaryResult, event: EventCandidate
    ) -> ResolvedEvent:
        return ResolvedEvent(
            start_pts=boundary.trigger_pts,
            end_pts=boundary.resolution_pts,
            peak_pts=boundary.peak_pts,
            peak_score=event.peak_score,
            keywords=[],
            transcript_excerpt="",
            draft_highlight_id=event.draft_highlight_id,
        )
