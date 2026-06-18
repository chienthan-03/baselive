# MVP Signal Layer Completion — Technical Design

> **Version:** 1.0  
> **Date:** 2026-06-18  
> **Status:** Approved (brainstorming session)  
> **Parent spec:** `docs/superpowers/specs/2026-06-17-livestream-highlight-extraction-design.md`  
> **Builds on:** Phase 1.1–1.6 (complete, 30/30 tests)  
> **Goal:** Close MVP gaps in PHẦN 2 (Realtime Processing Pipeline) before Phase 2 Beta

---

## 1. Problem Statement

Phase 1.1–1.6 delivered an end-to-end skeleton (ingestion → pipeline → clip → dashboard), but signal quality is far below the parent spec:

| Gap | Current | Spec target (PHẦN 2) |
|---|---|---|
| STT | Stub, not wired | Realtime transcript → TranscriptBuffer → scoring |
| Audio DSP | Energy + silence only | + pitch, laughter heuristic, speaker overlap |
| Chat analysis | Volume + keywords | + emoji categories, gift, spam filter, field fix |
| SignalSnapshot | 6 fields | Full §2.1.5 schema |
| Aggregator | 3-weight linear sum | excitement_score formula §2.1.6 + bonuses |
| Video for clips | Audio-only ingestion | Rolling `.mp4` file for ClipGenerator |
| State machine | Inline, basic | Extracted module + forced close + chat cooldown |

This phase completes the signal layer so highlight detection works on real signal diversity (audio + transcript + chat), not just loud audio + chat volume.

---

## 2. Decisions (locked in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Video recording | Rolling `.mp4` on disk | Simple, matches ClipGenerator, unblocks live clips |
| STT model | `faster-whisper` `small`, CPU, `int8` | Balance latency vs accuracy on dev hardware |
| Laughter detection | Spectral heuristic (no SVM) | YAGNI for MVP; SVM deferred to Phase 2 |
| Look-back expansion | Deferred | Phase 2 Beta scope |
| VideoBuffer TS segments | Not in scope | Rolling file chosen instead |
| Graceful degrade | Required | Pipeline runs with any subset of signal sources |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     StreamWorker (updated)                   │
│                                                              │
│  StreamRecorder ──┬──▶ AudioRingBuffer ──▶ STTWorker        │
│  (yt-dlp|ffmpeg)  │                              │           │
│                   │                              ▼           │
│                   │                      TranscriptBuffer    │
│                   │                                          │
│                   └──▶ rolling live.mp4 ──▶ ClipGenerator    │
│                                                              │
│  ChatCollector ──▶ ChatBuffer                                │
│                                                              │
│  Every 5s: MasterPipeline.process_chunk(...)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   MasterPipeline (updated)                   │
│                                                              │
│  AudioAnalyzer  → energy, pitch, silence, laughter, overlap│
│  STTAnalyzer    → speaking_rate, keywords, sentiment       │
│  ChatAnalyzer   → volume, emoji, gift, keywords, spam       │
│         │                                                    │
│         ▼                                                    │
│  SignalAggregator → excitement_score (spec §2.1.6)           │
│         │                                                    │
│         ▼                                                    │
│  StateMachine → IDLE → OPENING → ACTIVE → CLOSED             │
│         │                                                    │
│         ▼ (on CLOSED)                                        │
│  ClipGenerator(live.mp4) + Database.insert_highlight         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Component Specifications

### 4.1 StreamRecorder — dual output

**Change:** FFmpeg outputs both audio PCM (stdout) and rolling video file (disk).

```
yt-dlp → ffmpeg -i pipe:0
           ├── f32le PCM 16kHz mono → stdout → AudioRingBuffer
           └── copy codec → output/streams/{stream_id}/live.mp4
```

**New properties:**
- `video_path: str` — current recording file path
- `pts_offset: float` — PTS base when file was rotated

**Video write flags:** `-movflags +frag_keyframe+empty_moov` for read-while-write.

**Rotation:** New file every 30 min or when size > 500 MB. Increment `pts_offset` by elapsed duration.

### 4.2 STTWorker + STTAnalyzer

**STTWorker** returns structured output:

```python
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
```

**Config:** `model_size="small"`, `device="cpu"`, `compute_type="int8"`, `language="vi"`, `beam_size=1`.

**Chunking:** 5s audio, 0.5s overlap retained internally for boundary words.

**STTAnalyzer** (`src/pipeline/stt_analyzer.py`):
- `speaking_rate` — word_count × 1.5 / duration (Vietnamese syllable heuristic)
- `keyword_triggered` — regex + keyword sets from spec PHẦN 3
- `sentiment_shift` — rule-based positive/negative keyword lists (-1.0 to 1.0)
- `sentence_rate` — sentence count / 10s window

### 4.3 AudioAnalyzer extensions

| Signal | Method | Output |
|---|---|---|
| Pitch | Autocorrelation F0 per 100ms frame | `pitch_deviation` 0–1 vs rolling baseline |
| Laughter | HF energy ratio + periodic burst pattern | `laughter_prob` 0–1 |
| Speaker overlap | Energy variance across 100ms frames | `speaker_overlap` 0–1 |

Existing `energy_score`, `energy_spike`, `silence_before` unchanged.

### 4.4 ChatAnalyzer extensions

**Field fix:** `text = m.get("content") or m.get("msg", "")` — bridge emits `content`.

| Feature | Logic |
|---|---|
| Emoji categories | FUNNY/SHOCK/LOVE/SAD emoji sets, normalized per message count |
| Gift detector | `event_type == "GIFT"` → score from `gift_value` |
| Keyword clusters | HYPE/SHOCK/DRAMA; score when ≥3 msgs share cluster in 5s |
| Spam filter | Drop exact-text repeats >3; drop >5 msgs/user/5s |

### 4.5 SignalSnapshot (extended)

```python
@dataclass
class SignalSnapshot:
    pts: float
    # Audio
    audio_energy: float = 0.0
    audio_energy_spike: bool = False
    silence_before: float = 0.0
    pitch_deviation: float = 0.0
    speaking_rate: float = 0.0
    speaker_overlap: float = 0.0
    laughter_prob: float = 0.0
    # Transcript
    transcript_text: str = ""
    sentiment_shift: float = 0.0
    keyword_triggered: List[str] = field(default_factory=list)
    sentence_rate: float = 0.0
    # Chat
    chat_volume_spike: float = 0.0
    chat_emoji_scores: Dict[str, float] = field(default_factory=dict)
    chat_keyword_cluster: Optional[str] = None
    gift_event: Optional[Dict] = None
    # Aggregate
    composite_score: float = 0.0
```

### 4.6 SignalAggregator — excitement formula

Per spec §2.1.6:

```
excitement = 0.25*energy + 0.20*laughter + 0.15*chat_volume
           + 0.15*speaking_rate + 0.10*pitch + 0.10*emoji_dominant
           + 0.05*overlap

Bonuses:
  silence_before > 2s AND energy_spike → ×1.5
  keyword_triggered non-empty → ×1.3
  gift_value > big_gift_threshold (default 100) → ×1.4
```

Each component normalized 0–1 via rolling min-max over last 60 snapshots (~5 min at 5s chunks).

When a signal source is disabled, its weight is redistributed proportionally among enabled sources.

### 4.7 StateMachine (extracted)

**File:** `src/engine/state_machine.py`

| Rule | Value |
|---|---|
| OPEN_THR | 0.5 |
| CONFIRM_THR | 0.65 |
| CLOSE_THR | 0.25 |
| OPENING_TIMEOUT | 8s |
| CLOSE_COOLDOWN | 5s |
| MAX_EVENT_DURATION | 600s (forced close) |
| Chat cooldown | ACTIVE→CLOSED requires chat volume < 1.5× baseline |

**New:** `event.signals: List[SignalSnapshot]` — append each tick.

### 4.8 StreamWorker + MasterPipeline wiring

**StreamWorker additions:**
- `TranscriptBuffer(capacity_sec=900)`
- `STTWorker` with try/except `load_model()`
- Pass `transcript_items` and `recorder.video_path` to pipeline each chunk

**MasterPipeline.process_chunk()** signature:

```python
def process_chunk(
    self,
    pts: float,
    audio_data: np.ndarray,
    chat_messages: List[Dict],
    transcript: List[Dict] = None,
    clip_source: str = "",
) -> None:
```

Internally: AudioAnalyzer → STTAnalyzer → ChatAnalyzer → populate SignalSnapshot → Aggregator → StateMachine.

---

## 5. Error Handling

| Failure | Behavior |
|---|---|
| STT model not loaded | `stt_enabled=False`, transcript weights = 0 |
| STT backlog (>1 queued chunk) | Skip newest chunk, log warning |
| FFmpeg video write fails | Audio continues; `video_path=None`, clip skipped |
| yt-dlp disconnect | Existing reconnect backoff (1→30s, max 5) |
| Chat bridge dies | Audio+STT only |
| ClipGenerator FFmpeg error | Log stderr, highlight saved with empty `clip_path` |
| Video file rotation | `ClipGenerator` uses `pts - recorder.pts_offset` for seek |

**Principle:** No single signal source failure crashes the worker.

---

## 6. Testing Strategy

Target: **~45–50 total tests** (+15–20 new).

| Module | New test focus |
|---|---|
| StreamRecorder | video_path, dual-output cmd, rotation |
| STTWorker | TranscriptResult structure, segments |
| STTAnalyzer | speaking_rate, keywords, sentiment |
| AudioAnalyzer | pitch, laughter, overlap |
| ChatAnalyzer | emoji, gift, spam, content field |
| SignalAggregator | excitement formula, bonuses, degrade |
| StateMachine | forced close, chat cooldown, signals history |
| StreamWorker | STT + transcript wiring (mocked) |
| MasterPipeline | full snapshot, dynamic clip_source |
| Integration | audio spike + gift + transcript keywords → ACTIVE |

Live TikTok E2E and real faster-whisper inference are manual QA, not CI.

---

## 7. Success Criteria

Phase 1.7 is **DONE** when:

1. All tests pass (existing 30 + new ~15–20)
2. Signal layer matches spec §2.1.1–2.1.6 (minus video analysis, SVM laughter, look-back)
3. Rolling video records from StreamRecorder; ClipGenerator seeks correct PTS
4. STT wired — transcript signals affect composite_score
5. Graceful degrade verified: STT disabled → pipeline still detects from audio+chat
6. Dashboard API unchanged and working

---

## 8. Out of Scope

- Live TikTok E2E test (manual)
- Dynamic context expansion (Phase 2)
- VideoBuffer TS segments
- PhoWhisper / GPU STT
- LLM gate, feedback loop
- SVM laughter classifier
- Video analysis (OpenCV scene change)

---

## 9. Implementation Phases

| Phase | Scope |
|---|---|
| 1.7a | StreamRecorder video output |
| 1.7b | STT structured output + STTAnalyzer + TranscriptBuffer |
| 1.7c | AudioAnalyzer extensions |
| 1.7d | ChatAnalyzer full |
| 1.7e | SignalSnapshot + SignalAggregator rewrite |
| 1.7f | StateMachine extract + StreamWorker/MasterPipeline integration |

See implementation plan: `docs/superpowers/plans/2026-06-18-mvp-signal-layer-plan.md`
