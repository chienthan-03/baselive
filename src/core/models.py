from dataclasses import dataclass, field
from typing import List, Optional, Dict

@dataclass
class SignalSnapshot:
    pts: float
    
    # Audio signals (Basic phase)
    audio_energy: float = 0.0
    audio_energy_spike: bool = False
    silence_before: float = 0.0
    
    # STT & Chat signals (Phase 1.2)
    sentiment_shift: float = 0.0
    chat_volume_spike: float = 0.0
    
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
