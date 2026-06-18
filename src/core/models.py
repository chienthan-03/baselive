from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Dict

@dataclass
class SignalSnapshot:
    pts: float

    # Audio signals
    audio_energy: float = 0.0
    audio_energy_spike: bool = False
    silence_before: float = 0.0
    pitch_deviation: float = 0.0
    speaking_rate: float = 0.0
    speaker_overlap: float = 0.0
    laughter_prob: float = 0.0

    # Transcript signals
    transcript_text: str = ""
    sentiment_shift: float = 0.0
    keyword_triggered: List[str] = field(default_factory=list)
    sentence_rate: float = 0.0

    # Chat signals
    chat_volume_spike: float = 0.0
    chat_emoji_scores: Dict[str, float] = field(default_factory=dict)
    chat_keyword_cluster: Optional[str] = None
    gift_event: Optional[Dict] = None

    # Video signals
    video_scene_change: float = 0.0
    video_motion: float = 0.0

    # Aggregate
    composite_score: float = 0.0

@dataclass
class ClosedEventInfo:
    event: "EventCandidate"
    close_pts: float

@dataclass
class EventCandidate:
    state: str = "IDLE"
    start_pts: float = 0.0
    end_pts: float = 0.0
    peak_pts: float = 0.0
    peak_score: float = 0.0
    below_close_since: float = 0.0
    signals: List[SignalSnapshot] = field(default_factory=list)
    draft_highlight_id: Optional[int] = None
    refined_start_pts: Optional[float] = None
    refined_end_pts: Optional[float] = None
    content_type: Optional[str] = None
    quality: str = "partial"
    is_growing: bool = False

@dataclass
class BoundaryResult:
    trigger_pts: float
    resolution_pts: float
    peak_pts: float
    quality: str
    context_status: str
    stop_reason: str

@dataclass
class ResolvedEvent:
    start_pts: float
    end_pts: float
    peak_pts: float
    peak_score: float
    keywords: List[str]
    transcript_excerpt: str
    draft_highlight_id: Optional[int] = None
    sub_events: List["ResolvedEvent"] = field(default_factory=list)

@dataclass
class AmbiguousPair:
    event_a: ResolvedEvent
    event_b: ResolvedEvent
    similarity: float

@dataclass
class ResolutionResult:
    events: List[ResolvedEvent]
    ambiguous_pairs: List[AmbiguousPair]

@dataclass
class MicroHighlight:
    start_pts: float
    end_pts: float
    peak_pts: float
    peak_score: float
    parent_id: Optional[int] = None
    pre_roll: Optional[float] = None
    post_roll: Optional[float] = None

@dataclass
class ThresholdSet:
    open_thr: float
    confirm_thr: float
    close_thr: float
    peak_thr: float

class EventHistoryStore:
    max_size: int = 10

    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self._events: Deque[ResolvedEvent] = deque(maxlen=max_size)

    def append(self, event: ResolvedEvent) -> None:
        self._events.append(event)

    def get_overlapping(self, start_pts: float, end_pts: float) -> List[ResolvedEvent]:
        return [
            e for e in self._events
            if start_pts <= e.end_pts and end_pts >= e.start_pts
        ]

    def contains_pts(self, pts: float) -> Optional[ResolvedEvent]:
        for event in reversed(self._events):
            if event.start_pts <= pts <= event.end_pts:
                return event
        return None

@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    confidence: float

@dataclass
class TranscriptResult:
    text: str
    segments: List[TranscriptSegment]
    language: str
    chunk_start_pts: float
