from dataclasses import dataclass, field
from typing import List, Optional, Dict

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

    # Aggregate
    composite_score: float = 0.0

@dataclass
class EventCandidate:
    state: str = "IDLE"
    start_pts: float = 0.0
    end_pts: float = 0.0
    peak_pts: float = 0.0
    peak_score: float = 0.0
    below_close_since: float = 0.0
    signals: List[SignalSnapshot] = field(default_factory=list)

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
