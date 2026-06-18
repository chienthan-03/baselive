# Phase 2 Beta — Highlight Accuracy & Learning — Technical Design

> **Version:** 1.0  
> **Date:** 2026-06-18  
> **Status:** Approved (brainstorming session)  
> **Parent spec:** `docs/superpowers/specs/2026-06-17-livestream-highlight-extraction-design.md`  
> **Builds on:** Phase 1.1–1.7 (complete, 47/47 tests)  
> **Goal:** Improve highlight accuracy for daily editor use — correct boundaries, fewer false positives, clean event separation, and a feedback loop that learns from corrections.

---

## 1. Problem Statement

Phase 1 delivers end-to-end highlight detection (signal layer → state machine → clip → dashboard), but editors hit three core quality problems:

| Pain point | Current behavior | Target |
|---|---|---|
| **Wrong boundaries** | Fixed `pre_roll=10s` / `post_roll=5s` from state machine `start_pts`/`end_pts` | Dynamic look-back/forward + LLM refinement |
| **False positives** | Static thresholds from stream start | 3-tier cold start calibration + feedback-driven tuning |
| **Overlapping / long events** | Single event per CLOSED transition, max 600s forced close | Overlap resolution + multi-peak splitting (TikTok 15–60s) |

Phase 1.7 deferred these items explicitly. Phase 2 Beta closes them before Phase 3 (production scale / multi-platform).

---

## 2. Decisions (locked in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Priority order** | 2a → 2c → 2b → 2d | Boundaries first (biggest editor pain), then event hygiene, then learning, then ops |
| **LLM provider** | OpenRouter (`google/gemini-2.0-flash-001`) | User has API key; spec §5C budget fits |
| **Clip export model** | Draft + Final (PHẦN 8A) | Early preview while event grows; accurate clip after refine |
| **Architecture** | Modular `src/engine/` + `HighlightProcessor` orchestrator | Matches Phase 1 patterns; testable per sub-phase |
| **Topic similarity** | Keyword Jaccard overlap | No embeddings in Phase 2 (Phase 4 scope) |
| **Video buffer** | Keep rolling `.mp4` | TS segment buffer deferred; seek via `pts_offset` |
| **Global signal history** | New `SignalHistoryBuffer` (5 min) | Look-back needs data before event OPENING |
| **Chat lag / multi-stream** | Phase 2d (last) | Operational; not primary pain point |

---

## 3. Architecture

### 3.1 Data flow

```
StreamWorker
  │
  ├─▶ MasterPipeline.process_chunk() every 5s
  │     ├─▶ SignalHistoryBuffer.append(snapshot)
  │     ├─▶ StateMachine.process()
  │     │
  │     ├─ first ACTIVE → create DRAFT highlight + draft clip
  │     └─ CLOSED → look_forward (blocking) → enqueue PendingEventQueue
  │
  └─▶ HighlightProcessor (when pending queue ready)
        ├─ ContextExpander.look_back (per event)
        ├─ LLMGate Pass 1: refine boundary (if triggered)
        ├─ EventResolver.resolve (batch) → ambiguous_pairs
        ├─ LLMGate Pass 2: resolve_overlap (ambiguous pairs)
        ├─ EventSplitter.split (if duration > 180s)
        └─ generate FINAL clip(s) → update DB

Dashboard ◀── SQLite ◀── DRAFT / FINAL highlights
  │
  └─ approve / reject / modify → highlight_feedback → FeedbackLearner (daily batch)
        └─▶ BaselineCalibrator threshold updates
```

### 3.2 New modules

| File | Responsibility |
|---|---|
| `src/buffer/signal_history.py` | Global ring buffer of `SignalSnapshot` (5 min) |
| `src/engine/context_expander.py` | Look-back / look-forward boundary detection |
| `src/engine/llm_gate.py` | OpenRouter boundary refinement |
| `src/engine/event_resolver.py` | Overlap / nested / adjacent resolution |
| `src/engine/pending_event_queue.py` | Batch CLOSED events before resolve |
| `src/engine/event_splitter.py` | Long event → micro-highlights |
| `src/engine/baseline_calibrator.py` | 3-tier cold start thresholds |
| `src/engine/feedback_learner.py` | Daily learning from editor feedback |
| `src/engine/highlight_processor.py` | Post-CLOSED orchestrator |
| `src/pipeline/chat_lag.py` | Chat timestamp lag compensation |
| `src/ingestion/stream_manager.py` | Up to 3 concurrent streams |
| `src/jobs/feedback_daily.py` | CLI entry for daily batch job |
| `config/global_prior.json` | Seed global baseline statistics |

### 3.3 Implementation sub-phases

| Sub-phase | Scope | Est. |
|---|---|---|
| **2a** | `SignalHistoryBuffer`, `ContextExpander`, `LLMGate`, Draft/Final lifecycle, `ClipGenerator` + DB + dashboard updates | 2–3 wk |
| **2c** | `EventResolver`, `EventSplitter`, `HighlightProcessor` wiring | 1.5–2 wk |
| **2b** | `BaselineCalibrator`, `highlight_feedback` table, `FeedbackLearner`, reject-reason UI | 2–2.5 wk |
| **2d** | `ChatLagCompensator`, `StreamManager`, stream filter API/UI | 1 wk |

---

## 4. Component Specifications

### 4.1 SignalHistoryBuffer

Ring buffer storing every `SignalSnapshot` regardless of state machine state.

```python
@dataclass
class HistoryEntry:
    snapshot: SignalSnapshot
    pts: float

class SignalHistoryBuffer:
    capacity_sec: int = 300  # 5 min = default MAX_LOOKBACK

    def append(self, snapshot: SignalSnapshot) -> None: ...
    def get_at(self, pts: float) -> Optional[SignalSnapshot]: ...  # nearest ±2.5s
    def get_range(self, start_pts: float, end_pts: float) -> List[HistoryEntry]: ...
    def oldest_pts(self) -> float: ...
```

**Integration:** `MasterPipeline.process_chunk()` calls `append()` after each tick. `ContextExpander` reads look-back from here — not from `event.signals` (which only accumulates from current event cycle).

---

### 4.2 ContextExpander

Refines `trigger_pts` (look-back from peak) and `resolution_pts` (look-forward from close).

```python
@dataclass
class BoundaryResult:
    trigger_pts: float
    resolution_pts: float
    peak_pts: float
    quality: str          # "complete" | "possibly_incomplete" | "buffer_limited" | "forced_close"
    context_status: str   # "FULL" | "PARTIAL"
    stop_reason: str

class ContextExpander:
    MAX_LOOKBACK = 300.0
    MAX_LOOKFORWARD = 120.0
    STEP_SEC = 1.0

    def look_back(self, peak_pts: float, history: SignalHistoryBuffer,
                  transcript: TranscriptBuffer,
                  event_history: EventHistoryStore) -> float: ...

    def look_forward(self, peak_pts: float, close_pts: float,
                     history: SignalHistoryBuffer,
                     transcript: TranscriptBuffer) -> float: ...

    def expand(self, event: EventCandidate, ...) -> BoundaryResult: ...
```

#### Look-back stop conditions (priority order)

| # | Condition | Action |
|---|---|---|
| a | `t < peak - 300s` | Stop; `quality="possibly_incomplete"` |
| b | `t < oldest_buffer_pts` | Stop; `quality="buffer_limited"`, `context_status="PARTIAL"` |
| c | Silence > 3s and `t < peak - 5s` | Trigger candidate; verify 5s before silence is event-related |
| d | Topic change (keyword Jaccard < 0.3 vs peak window) | Stop at `t + 1s` |
| e | Score < 0.15 for ≥ 5s continuous + different topic | Stop at last point before score rose |
| f | `t` inside a previously CLOSED event | Stop at previous event `end_pts` |

**Prior event source for condition (f):** `EventHistoryStore` — an in-memory deque on `HighlightProcessor` holding the last 10 `ResolvedEvent` records (start/end/peak PTS). Populated after each CLOSED event is fully processed. `ContextExpander.look_back()` receives this store as a parameter. Not read from DB (latency); DB is write-only for highlights.

#### Look-forward stop conditions (realtime, blocking in StreamWorker)

| # | Condition | Action |
|---|---|---|
| a | `t > peak + 120s` | `quality="forced_close"` |
| b | Score < 0.25 for ≥ 5s + chat < 1.5× baseline | Resolution = `t - 2s` |
| c | Topic shift | Resolution = `t - 1s` |
| d | New event OPENING | Resolution = `t - 1s`; new event starts |
| e | Silence > 5s + energy at baseline | Resolution = start of silence |

#### Topic similarity

```
jaccard = |keywords_A ∩ keywords_B| / |keywords_A ∪ keywords_B|
```

Keywords from `keyword_triggered` + tokenized transcript text in a 10s window around each PTS.

#### Partial buffer handling

When `trigger_pts < oldest_video_pts`:
1. Set `context_status = "PARTIAL"`
2. Clip starts from oldest available video PTS
3. Store transcript context in `reason` field for editor alert
4. Text overlay deferred to Phase 3

---

### 4.3 LLMGate

OpenRouter API for semantic boundary refinement. Env: `OPENROUTER_API_KEY`.

#### Trigger conditions

**Pass 1 — boundary refinement** (`task: refine_highlight_boundary`), evaluated in `HighlightProcessor` step 2, before `EventResolver`:

| # | Condition |
|---|---|
| a | Event CLOSED and `peak_score > 0.7` |
| b | Duration > 180s |
| c | Editor explicit request via API |

**Pass 2 — overlap resolution** (`task: resolve_overlap`), evaluated in `HighlightProcessor` step 4, after `EventResolver` detects ambiguous overlap (similarity 0.3–0.7):

| # | Condition |
|---|---|
| d | `EventResolver` returns an ambiguous pair (similarity 0.3–0.7) |

There is no separate trigger for "2+ overlapping events" outside these two passes. Overlap LLM is only called for ambiguous pairs, not for clear merge/trim decisions.

#### Rate limits (spec §5C)

```python
MAX_CALLS_PER_HOUR = 10
MIN_GAP_SEC = 30
DAILY_BUDGET_USD = 5.0
MODEL = "google/gemini-2.0-flash-001"
```

#### Input / output

**Input:**
```json
{
  "task": "refine_highlight_boundary",
  "transcript": "<5 min transcript around event>",
  "signals_summary": {
    "peak_pts": 120.0,
    "peak_score": 0.85,
    "energy_curve": [],
    "chat_spikes": [],
    "keywords": ["ôi", "trời ơi"]
  },
  "current_boundary": { "start": 95.0, "end": 145.0 },
  "language": "vi"
}
```

**Output:**
```json
{
  "refined_start_pts": 98.5,
  "refined_end_pts": 142.0,
  "content_type": "funny",
  "confidence": 0.82,
  "reasoning": "..."
}
```

**Fallback:** On timeout, 429, or budget exceeded → keep `ContextExpander` boundary, log warning, proceed with final clip generation.

**Overlap task:** When `topic_similarity` is 0.3–0.7 (ambiguous), call with `task: "resolve_overlap"`.

---

### 4.4 Draft / Final lifecycle

Per parent spec PHẦN 8A.

#### EventCandidate extensions

```python
@dataclass
class EventCandidate:
    # existing fields...
    draft_highlight_id: Optional[int] = None
    refined_start_pts: Optional[float] = None
    refined_end_pts: Optional[float] = None
    content_type: Optional[str] = None
    quality: str = "partial"
    is_growing: bool = False
```

#### Database schema extensions

```sql
ALTER TABLE highlights ADD COLUMN highlight_type TEXT DEFAULT 'FINAL';
ALTER TABLE highlights ADD COLUMN is_growing INTEGER DEFAULT 0;
ALTER TABLE highlights ADD COLUMN quality TEXT DEFAULT 'complete';
ALTER TABLE highlights ADD COLUMN content_type TEXT;
ALTER TABLE highlights ADD COLUMN draft_clip_path TEXT;
ALTER TABLE highlights ADD COLUMN parent_id INTEGER;
ALTER TABLE highlights ADD COLUMN peak_pts REAL;
ALTER TABLE highlights ADD COLUMN ai_start_pts REAL;
ALTER TABLE highlights ADD COLUMN ai_end_pts REAL;
```

`highlight_type`: `DRAFT` | `FINAL`

#### Lifecycle

**Draft creation rule:** Exactly **one** DRAFT row per event. Created once on the **first transition to ACTIVE** (OPENING → ACTIVE), not on every subsequent `peak_score` update. `draft_highlight_id` on `EventCandidate` prevents duplicate inserts.

```
OPENING → ACTIVE (first time)
  → INSERT highlight (type=DRAFT, status=PENDING, is_growing=1)
  → store draft_highlight_id on EventCandidate
  → generate draft clip (full pre_roll, post_roll=0, end=current_pts)

While ACTIVE (peak_score may update)
  → UPDATE same DRAFT row (score, peak_pts) — no new INSERT
  → regenerate draft clip every 30s (configurable, default on) with updated end_pts

CLOSED
  → SET is_growing=0 on existing DRAFT row
  → StreamWorker runs look_forward (blocking)
  → HighlightProcessor refines boundary
  → UPGRADE same DRAFT row → FINAL (see upgrade rules below)
  → generate final clip with refined boundaries + full post_roll
```

#### DRAFT → FINAL upgrade rules

| Case | Action |
|---|---|
| Single event, no split | UPDATE existing DRAFT row: `highlight_type=FINAL`, refined boundaries, final clip path |
| Event split into micro-highlights | UPDATE DRAFT row to FINAL (parent); INSERT child rows (`parent_id=parent`, `highlight_type=FINAL`) for each micro-highlight |
| MERGE of two events | Keep DRAFT of higher-score event as FINAL; mark other DRAFT as `status=MERGED` (hidden from queue) |

#### Status vs type (two-axis model)

| Field | Values | Meaning |
|---|---|---|
| `highlight_type` | `DRAFT`, `FINAL` | Pipeline processing stage |
| `status` | `PENDING`, `APPROVED`, `REJECTED`, `ADJUSTED`, `MERGED` | Editor decision |

`EXPORTED` status is out of scope for Phase 2 Beta (no publish workflow yet).

#### ClipGenerator changes

```python
def generate_draft(self, event: EventCandidate, end_pts: float) -> str:
    # pre_roll full, post_roll=0, end=end_pts

def generate_final(self, start_pts: float, end_pts: float, event: EventCandidate) -> str:
    # refined boundary, pre_roll + post_roll full
```

#### Safeguards (PHẦN 8B)

| Rule | Action |
|---|---|
| Draft duration < 10s | Do not show in UI |
| Draft duration < 15s | Show with "very short" warning |
| `is_growing=true` | Disable approve/export; bookmark only |
| Forced close at 600s | `quality="forced_close"`; alert editor to split manually |
| Post-peak cooldown | Disable approve/export for 10s after peak (PHẦN 8B); draft still visible |

---

### 4.5 EventResolver

Resolves overlap between multiple CLOSED events before final clip generation.

#### PendingEventQueue

Events are not finalized immediately on CLOSED. They enter a pending queue and are batch-resolved when ready:

```python
class PendingEventQueue:
    MAX_WAIT_SEC = 30.0  # wait for adjacent event before finalizing alone

    def enqueue(self, event: ResolvedEvent) -> None: ...
    def is_ready(self, current_pts: float) -> bool:
        # True if len >= 2 OR oldest event waited >= MAX_WAIT_SEC
    def drain(self) -> List[ResolvedEvent]: ...
```

**Enqueue timing:** After `ContextExpander` + look-forward on CLOSED, `StreamWorker` calls `enqueue(to_resolved(boundary))`. If `is_ready()`, invoke `HighlightProcessor.process_pending_queue()`.

**Timeout polling:** `MasterPipeline.process_chunk()` also checks `pending_queue.is_ready(current_pts)` every 5s tick so a lone event drains after `MAX_WAIT_SEC` without requiring a second CLOSED event.

**Rationale:** Adjacent events (< 5s gap) need both boundaries present to decide MERGE vs KEEP_BOTH. Single events finalize after 30s wait.

#### Resolution types

```python
@dataclass
class AmbiguousPair:
    event_a: ResolvedEvent
    event_b: ResolvedEvent
    similarity: float

@dataclass
class ResolutionResult:
    events: List[ResolvedEvent]
    ambiguous_pairs: List[AmbiguousPair]

class EventResolver:
    ADJACENT_GAP_SEC = 5.0
    TOPIC_MERGE_THRESHOLD = 0.7
    TOPIC_SEPARATE_THRESHOLD = 0.3
    SCORE_RATIO_SUBORDINATE = 3.0

    def resolve(self, events: List[ResolvedEvent]) -> ResolutionResult: ...
    def topic_similarity(self, a: ResolvedEvent, b: ResolvedEvent) -> float: ...
```

`ambiguous_pairs` contains pairs with similarity in (0.3, 0.7) that were not auto-resolved. Passed to `LLMGate.resolve_overlap()` in HighlightProcessor step 4.

#### Resolution matrix (keyword Jaccard)

| Situation | Action |
|---|---|
| OVERLAP + similarity > 0.7 | MERGE; keep higher peak score |
| OVERLAP + similarity < 0.3 | KEEP_BOTH; trim at midpoint |
| OVERLAP + score ratio > 3.0 | SUBORDINATE smaller event |
| NESTED + same topic | SUBORDINATE inner event |
| NESTED + different topic | KEEP_BOTH; inner is separate event |
| ADJACENT gap < 5s + same topic | MERGE |
| ADJACENT gap < 5s + different topic | KEEP_BOTH |

Ambiguous similarity (0.3–0.7) → included in `ResolutionResult.ambiguous_pairs` for `LLMGate` Pass 2 (not resolved inline).

---

### 4.6 EventSplitter

Splits events longer than `MAX_SINGLE_HIGHLIGHT` into TikTok-targeted micro-highlights.

```python
MAX_SINGLE_HIGHLIGHT = 180.0
MIN_PROMINENCE = 0.3
MIN_PEAK_DISTANCE = 15.0
TIKTOK_TARGET = 45.0
TIKTOK_MAX = 60.0
TIKTOK_MIN = 15.0
MERGE_GAP = 5.0

class EventSplitter:
    def split(self, event: ResolvedEvent, history: SignalHistoryBuffer,
              platform: str = "tiktok") -> List[MicroHighlight]: ...
```

#### Algorithm

1. If duration ≤ 180s → return single highlight unchanged
2. Build `score_curve` from `SignalHistoryBuffer.get_range(event.start_pts, event.end_pts)` → composite_score per snapshot
3. `find_local_maxima(score_curve, min_prominence=0.3, min_distance=15s)`
3. If ≥ 2 peaks → create `MicroHighlight` per peak (valley before/after as boundaries)
4. Merge micro-highlights with gap < 5s
5. Discard clips < 15s; re-split clips > 60s at valley
6. Each micro-highlight → separate DB row with `parent_id` pointing to original event

**TikTok roll values when split:** `pre_roll=2s`, `post_roll=1s` (override global 10s/5s).

---

### 4.7 BaselineCalibrator (Cold Start)

3-tier baseline strategy per parent spec §4A.

| Phase | Time | Mode | OPEN_THR behavior |
|---|---|---|---|
| 0 | 0–60s | Global prior | `global_open * 0.8` (favor recall) |
| 1 | 60–300s | Hybrid blend | `lerp(phase0, calibrated, weight)` |
| 2 | 300s+ | Stream calibrated | percentile-based (see below) |

**Threshold derivation per tier:**

| Threshold | Phase 0 (0–60s) | Phase 1 (60–300s) | Phase 2 (300s+) |
|---|---|---|---|
| `OPEN_THR` | `global_open * 0.8` | `lerp(phase0, p80, weight)` | percentile(composite, 80) |
| `CONFIRM_THR` | `global_confirm * 0.85` | `lerp(phase0, p90, weight)` | percentile(composite, 90) |
| `CLOSE_THR` | fixed `0.25` | `lerp(0.25, p30, weight)` | percentile(composite, 30) |
| `PEAK_THR` | `global_peak * 0.85` | `lerp(phase0, p95, weight)` | percentile(composite, 95) |

```python
@dataclass
class GlobalPrior:
    audio_energy_mean: float = 0.05
    audio_energy_std: float = 0.02
    chat_volume_mean: float = 8.0
    chat_volume_std: float = 3.0
    speaking_rate_mean: float = 3.5
    speaking_rate_std: float = 0.8

class BaselineCalibrator:
    def get_thresholds(self, elapsed_sec: float, rolling_stats) -> ThresholdSet: ...
    def detect_activity_change(self, stats_1min, stats_5min) -> bool: ...
    def recalibrate(self) -> None  # every 30s in phase 2
```

**Global prior file:** `config/global_prior.json` — seeded with reasonable defaults; updated by `FeedbackLearner` when sufficient session data exists.

**Activity change:** `|mean_1min - mean_5min| > 2 * std_5min` → reset calibration window; blend 50/50 for 2 minutes.

**Integration:** `StateMachine` receives dynamic `OPEN_THR`, `CONFIRM_THR`, `CLOSE_THR` from calibrator instead of hardcoded class constants.

---

### 4.8 FeedbackLearner

Captures editor decisions and applies daily threshold/roll adjustments.

#### `highlight_feedback` table

```sql
CREATE TABLE highlight_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  highlight_id INTEGER NOT NULL,
  stream_id TEXT NOT NULL,
  editor_id TEXT DEFAULT 'default',
  ai_start_pts REAL,
  ai_end_pts REAL,
  ai_score REAL,
  action TEXT NOT NULL,
  editor_start_pts REAL,
  editor_end_pts REAL,
  reject_reason TEXT,
  start_delta_sec REAL,
  end_delta_sec REAL,
  content_type TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

`action`: `ACCEPT` | `REJECT` | `MODIFY` | `SPLIT`

#### Capture triggers

| Editor action | Feedback recorded |
|---|---|
| `POST /approve` (no prior adjust) | `ACCEPT`, deltas = 0 |
| `POST /reject` with `{ "reason": "..." }` | `REJECT` + `reject_reason` |
| `POST /adjust` then `POST /approve` | `MODIFY` on adjust; `ACCEPT` with deltas on approve |
| `POST /adjust` alone | `MODIFY` with computed deltas |

**Reject reasons (UI dropdown):** `false_positive`, `wrong_boundary`, `too_short`, `too_long`, `wrong_moment`, `duplicate`, `other`

#### Daily batch (`python -m src.jobs.feedback_daily`)

1. `avg_start_delta` → adjust `pre_roll_default`
2. `avg_end_delta` → adjust `post_roll_default`
3. Accept rate by `content_type` → per-type sensitivity
4. Common `false_positive` rejects → bump `OPEN_THR`
5. Smoothing: `new = 0.7 * old + 0.3 * learned`

**Config persistence:** Learned values written to `config/stream_config.json` (per-stream overrides) and `config/global_prior.json` (global defaults). `BaselineCalibrator` and `ClipGenerator` read from these files on startup and after daily job runs.

**Minimum data gate:** Require ≥ 10 feedback entries before applying changes.

---

### 4.9 ChatLagCompensator (Phase 2d)

```python
class ChatLagCompensator:
    DEFAULT_LAG_TIKTOK = 5.0

    def adjust_message(self, msg: dict) -> dict:
        # msg["adjusted_pts"] = msg["pts"] - current_lag

    def calibrate_from_spike(self, audio_spike_pts: float, chat_spike_pts: float) -> None:
        # rolling average over last 10 spike pairs

    def cross_correlate_calibrate(self, audio_curve, chat_curve) -> None:
        # every 15 min; smoothed update 0.7 * old + 0.3 * new
```

**Integration:** `ChatAnalyzer` uses `adjusted_pts` for volume spike timing. `ChatBuffer` stores both `pts` and `adjusted_pts`.

**Scope:** Passive calibration + TikTok default 5s. Asymmetric lag by emotion type is behind a feature flag (default off).

---

### 4.10 StreamManager (Phase 2d)

```python
class StreamManager:
    MAX_CONCURRENT = 3

    def start_stream(self, url: str, stream_id: str) -> StreamWorker: ...
    def stop_stream(self, stream_id: str) -> None: ...
    def list_active(self) -> List[str]: ...
```

- One `StreamWorker` per stream (thread or subprocess)
- Dashboard stream filter dropdown
- API: `GET /api/streams`, `POST /api/streams/start`, `POST /api/streams/{id}/stop`
- Reject start when already at 3 concurrent (HTTP 429)

---

### 4.11 HighlightProcessor (Orchestrator)

```python
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

class EventHistoryStore:
    max_size: int = 10

    def append(self, event: ResolvedEvent) -> None: ...
    def get_overlapping(self, start_pts: float, end_pts: float) -> List[ResolvedEvent]: ...
    def contains_pts(self, pts: float) -> Optional[ResolvedEvent]: ...

@dataclass
class ThresholdSet:
    open_thr: float
    confirm_thr: float
    close_thr: float
    peak_thr: float

@dataclass
class MicroHighlight:
    start_pts: float
    end_pts: float
    peak_pts: float
    peak_score: float
    parent_id: Optional[int] = None

class HighlightProcessor:
    def __init__(self, context_expander, llm_gate, event_resolver,
                 event_splitter, clip_generator, db): ...
    self.event_history: EventHistoryStore
    self.pending_queue: PendingEventQueue

    def on_event_closed(
        self,
        event: EventCandidate,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        clip_source: str,
        resolution_pts: float,
        current_pts: float,
    ) -> None:
        # 1. boundary = context_expander.expand(event, resolution_pts, event_history)
        # 2. enqueue to_resolved(boundary) on pending_queue
        # 3. if pending_queue.is_ready(current_pts): process_pending_queue(...)

    def process_pending_queue(
        self,
        history: SignalHistoryBuffer,
        transcript: TranscriptBuffer,
        clip_source: str,
    ) -> List[HighlightRecord]:
        events = pending_queue.drain()
        # 4. for each event: if llm_gate.should_refine_boundary(e): refine
        # 5. result = event_resolver.resolve(events)
        # 6. for pair in result.ambiguous_pairs: apply llm_gate.resolve_overlap(pair)
        # 7. for each resolved event: splits = event_splitter.split(e, history)
        # 8. generate final clip(s); upgrade DRAFT → FINAL per §4.4 rules
        # 9. event_history.append(all finalized events)
        ...

    def to_resolved(self, boundary: BoundaryResult, event: EventCandidate) -> ResolvedEvent: ...
```

**Look-forward** runs in `StreamWorker` before calling processor (blocking wait on live stream ticks).

**State machine reset:** After processor completes, reset `StateMachine.current_event` to new `EventCandidate()` (fix: currently not reset after CLOSED in Phase 1).

---

## 5. API & Dashboard Changes

### 5.1 New / updated endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/highlights?type=DRAFT\|FINAL` | Filter by highlight type |
| `GET` | `/api/highlights?stream_id=X` | Filter by stream |
| `POST` | `/api/highlights/{id}/reject` | Body: `{ "reason": "false_positive" }`; writes `highlight_feedback` |
| `POST` | `/api/highlights/{id}/approve` | Updated: writes `highlight_feedback` on approve |
| `POST` | `/api/highlights/{id}/adjust` | Updated: writes `highlight_feedback` on adjust |
| `POST` | `/api/highlights/{id}/llm-analyze` | Editor-triggered LLM analysis |
| `GET` | `/api/streams` | List active streams |
| `POST` | `/api/streams/start` | Body: `{ "url", "stream_id" }` |
| `POST` | `/api/streams/{id}/stop` | Stop stream worker |

### 5.2 UI changes (`src/api/static/`)

- Badge **DRAFT** (amber) / **FINAL** (green) on queue items
- Banner "Event đang diễn ra — clip chưa hoàn chỉnh" when `is_growing`
- Disable Approve button when `is_growing=true`
- Reject modal with reason dropdown
- Display `content_type`, `quality` warnings
- Filter tabs: All / Draft / Final / Pending
- Stream selector dropdown (Phase 2d)

---

## 6. Error Handling

| Failure | Behavior |
|---|---|
| LLM timeout / 429 / budget exceeded | Keep rule-based boundary; log; generate final clip |
| Look-back hits buffer limit | `context_status=PARTIAL`; clip from oldest video PTS |
| Look-forward timeout 120s | `quality=forced_close`; use current close_pts |
| Split produces clip < 15s | Discard micro-highlight |
| Feedback < 10 entries | Skip learning update for that metric |
| StreamManager at capacity | HTTP 429 on start |
| `OPENROUTER_API_KEY` missing | `LLMGate.enabled=False`; degrade gracefully |
| FFmpeg draft/final gen fails | Save highlight with empty `clip_path`; log stderr |

**Principle:** No single failure crashes `StreamWorker`. Draft highlight is always creatable via rule-based path.

---

## 7. Testing Strategy

**Target:** ~75–85 total tests (+28–38 new).

| Module | Test focus |
|---|---|
| `SignalHistoryBuffer` | append, ring eviction, get_range, oldest_pts |
| `ContextExpander` | each stop condition, buffer_limited, partial context |
| `LLMGate` | trigger rules, rate limit, mock OpenRouter, fallback |
| Draft/Final lifecycle | state transitions, is_growing guards, DB upgrade |
| `EventResolver` | overlap, nested, adjacent, merge/trim/subordinate |
| `EventSplitter` | multi-peak, min duration filter, TikTok targets |
| `BaselineCalibrator` | 3-tier thresholds, activity change reset |
| `FeedbackLearner` | delta computation, min-data gate, smoothing |
| `ChatLagCompensator` | adjusted_pts, rolling calibration |
| `HighlightProcessor` | end-to-end with mocked dependencies |
| API | new endpoints, reject reason body, stream filter |
| Integration | audio spike → DRAFT → CLOSED → FINAL with refined boundary |

OpenRouter calls are mocked in CI. Manual QA with real API key for LLM boundary quality.

---

## 8. Success Criteria

Phase 2 Beta is **DONE** when:

1. All tests pass (~75–85 total)
2. Draft highlight appears within seconds of peak detection; Final clip generated after CLOSED + refine
3. Look-back extends trigger before state machine `start_pts` in test scenarios
4. LLM gate refines boundaries when triggered; degrades when API unavailable
5. Overlapping events resolved; events > 180s split into TikTok-length clips
6. Cold start: fewer false positives in first 5 minutes vs Phase 1 static thresholds (verified in test fixtures)
7. Editor reject/approve/modify captured in `highlight_feedback`; daily job updates thresholds
8. 3 concurrent streams runnable via `StreamManager`
9. Dashboard shows DRAFT/FINAL states with growing-event safeguards

---

## 9. Out of Scope

- VideoBuffer TS segments (keep rolling `.mp4`)
- Embedding-based topic detection (Phase 4)
- SVM laughter classifier, source separation, speaker diarization
- YouTube / Facebook platform adapters (Phase 3)
- Text overlay for partial context clips (Phase 3)
- Prometheus / Grafana monitoring (Phase 3)
- PostgreSQL migration (stay on SQLite for Beta)
- Virality prediction, A/B testing framework (Phase 4)

---

## 10. File Map (summary)

| File | Action | Sub-phase |
|---|---|---|
| `src/buffer/signal_history.py` | Create | 2a |
| `src/engine/context_expander.py` | Create | 2a |
| `src/engine/llm_gate.py` | Create | 2a |
| `src/engine/highlight_processor.py` | Create | 2a (stub) → 2c (full) |
| `src/engine/clip_generator.py` | Modify | 2a |
| `src/engine/pipeline.py` | Modify | 2a |
| `src/engine/state_machine.py` | Modify | 2a, 2b |
| `src/core/models.py` | Modify | 2a |
| `src/db/database.py` | Modify | 2a, 2b |
| `src/api/main.py` | Modify | 2a, 2b, 2d |
| `src/api/static/js/app.js` | Modify | 2a, 2b |
| `src/api/static/index.html` | Modify | 2a, 2b |
| `src/ingestion/stream_worker.py` | Modify | 2a |
| `src/engine/event_resolver.py` | Create | 2c |
| `src/engine/pending_event_queue.py` | Create | 2c |
| `src/engine/event_splitter.py` | Create | 2c |
| `src/engine/baseline_calibrator.py` | Create | 2b |
| `src/engine/feedback_learner.py` | Create | 2b |
| `src/jobs/feedback_daily.py` | Create | 2b |
| `config/global_prior.json` | Create | 2b |
| `src/pipeline/chat_lag.py` | Create | 2d |
| `src/pipeline/chat_analyzer.py` | Modify | 2d |
| `src/ingestion/stream_manager.py` | Create | 2d |
| `tests/**` | Create/Modify | all |

---

## 11. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Optional | Enables LLM gate; graceful degrade if missing |
| `OPENROUTER_MODEL` | Optional | Default: `google/gemini-2.0-flash-001` |
| `LLM_DAILY_BUDGET_USD` | Optional | Default: `5.0` |
