# Phase 3 — Production Readiness — Technical Design

> **Version:** 1.1  
> **Date:** 2026-06-18  
> **Status:** Approved (spec review iteration 1 fixes applied)  
> **Parent spec:** `docs/superpowers/specs/2026-06-17-livestream-highlight-extraction-design.md`  
> **Builds on:** Phase 1 (complete) + Phase 2 Beta (target: 116/116 tests)  
> **Goal:** Production-ready architecture — observable, extensible to multi-platform, worker-pool ready, CPU video signals — while still running 3–5 TikTok streams on a single local machine.

---

## 1. Problem Statement

Phase 2 Beta delivers accurate highlights for daily editor use on 1–3 TikTok streams. Phase 3 addresses operational gaps before scaling or multi-platform expansion:

| Gap | Current (Phase 2) | Target (Phase 3) |
|---|---|---|
| **No observability** | Logs only; no metrics dashboard | Prometheus `/metrics` + Grafana dashboards |
| **Monolithic stream manager** | `StreamManager` with hard `MAX_CONCURRENT=3`, thread-per-stream in API process | `Orchestrator` + `WorkerNode` abstraction; config-driven capacity |
| **TikTok-coupled ingestion** | `ChatCollector`, `StreamRecorder` assume TikTok | `PlatformAdapter` interface; TikTok production, YouTube/FB skeleton |
| **Audio/chat-only signals** | No video frame analysis | CPU-light scene change + motion scores |
| **No cost guardrails** | LLM gate exists but no budget tracking | Daily LLM budget cap + selective audio processing |
| **No backup** | Single `base_live.db` + local clips | Daily snapshot job + stream recovery on restart |

**Milestone:** System runs 3–5 TikTok streams stably on one machine with metrics, platform adapter layer, video signals, and automated backups. YouTube/Facebook adapters exist as skeletons only. Deploy target (local vs cloud) remains undecided — all components are deployment-abstract.

---

## 2. Decisions (locked in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Scope** | Full Phase 3 parent roadmap, decomposed into sub-phases | User confirmed full scope |
| **Deploy target** | Abstract — design for future cloud, default single-machine | Deploy undecided |
| **Platform priority** | TikTok production; YouTube/FB skeleton only | Team primarily uses TikTok |
| **Scale target** | Architecture-ready, 3–5 streams on 1 machine | Not prove 10-stream load test |
| **Monitoring** | Prometheus exporter + Grafana dashboards | Self-host optional |
| **Video analysis** | CPU lightweight — histogram frame diff + motion score | No GPU in Phase 3 |
| **Database** | Keep SQLite | Sufficient for 3–5 streams internal tool |
| **Sub-phase order** | 3a → 3c → 3b → 3d → 3e → 3f | Observability first; worker pool before adapters |
| **Message queue** | Deferred (Phase 4) | Redis/Kafka not needed at 3–5 streams |
| **PostgreSQL** | Deferred (Phase 4) | SQLite sufficient per user decision |

### 2.1 Prerequisites (gate before Phase 3 start)

Phase 3 assumes Phase 2 Beta source is present and green. **Do not start Phase 3 implementation until:**

| Prerequisite | Verification |
|---|---|
| Phase 2 modules in `src/` | `llm_gate.py`, `highlight_processor.py`, `context_expander.py`, `chat_lag.py`, `baseline_calibrator.py`, etc. |
| Draft/Final lifecycle | DRAFT on ACTIVE, FINAL via `HighlightProcessor` on CLOSED |
| `highlight_feedback` table + API capture | approve/reject/modify write feedback |
| Test suite | `pytest` → **116/116 pass** |

If Phase 2 source is missing from the repo, restore it before Phase 3a.

### 2.2 Deviations from parent spec (intentional)

| Parent spec (§12) | Phase 3 spec | Reason |
|---|---|---|
| Milestone: 10+ streams | 3–5 streams, architecture-ready | Deploy undecided; single-machine target |
| YouTube + Facebook production | Skeleton adapters only | TikTok primary per brainstorming |
| Prove multi-VM worker pool | Single `WorkerNode` default | Abstract for future cloud |
| Video analysis listed at scale tier | CPU lightweight only | No GPU; parent risk register defers GPU video |
| PostgreSQL at 10 streams | Keep SQLite | User decision |

---

## 3. Architecture

### 3.1 High-level diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI Application                                                 │
│  ├── Dashboard (static)                                              │
│  ├── /api/streams, /api/highlights, /api/health, /api/health/ready  │
│  └── /metrics (Prometheus)                                           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  OrchestratorService                                                 │
│  ├── WorkerNode[0]  (default: holds all streams on single machine) │
│  │     └── StreamWorker × N (max MAX_STREAMS_PER_NODE, default 5)  │
│  ├── StreamRegistry (SQLite `streams` table + in-memory state)       │
│  └── MetricsCollector (registers Prometheus metrics)                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   PlatformAdapter         MasterPipeline         VideoAnalyzer
   (per platform)          (Phase 2 + video       (owned by StreamWorker,
                           signal fields)          samples frames)
          │
   ┌──────┴──────┬──────────────┐
   │ TikTok ✅   │ YouTube stub │ Facebook stub │
   └─────────────┴──────────────┴───────────────┘
```

### 3.2 Data flow (unchanged core, new sidecars)

```
StreamWorker.run() loop (every 5s chunk)
  │
  ├─▶ StreamRecorder → audio_buffer
  ├─▶ ChatCollector (via PlatformAdapter in 3b; hardcoded TikTok in 3c interim) → chat_buffer
  ├─▶ STTWorker → transcript_buffer
  ├─▶ VideoAnalyzer.sample_frame(clip_source, pts)  [NEW, 3d]
  │     └─▶ compare with _prev_frame → video_scene_change, video_motion
  │
  └─▶ MasterPipeline.process_chunk(..., video_signals={...})
        ├─▶ audio_dsp + chat_analyzer + stt_analyzer
        ├─▶ SignalAggregator (includes video_scene_change, video_motion when present)
        ├─▶ StateMachine → DRAFT / CLOSED
        └─▶ HighlightProcessor → FINAL

MetricsCollector.observe_*() at each stage          [NEW, 3a]
OrchestratorService heartbeat daemon every 30s      [NEW, 3c]
```

**Video ownership:** `StreamWorker` owns `VideoAnalyzer` and `_prev_video_frame` (per-stream state). It passes computed `video_scene_change` / `video_motion` into `process_chunk()`. `MasterPipeline` does not call OpenCV directly.

### 3.3 New modules

| File | Responsibility |
|---|---|
| `src/observability/metrics.py` | Prometheus metric definitions + `MetricsCollector` |
| `src/observability/health.py` | Liveness/readiness checks |
| `src/ingestion/orchestrator.py` | Stream lifecycle, node assignment, recovery |
| `src/ingestion/worker_node.py` | Manages N `StreamWorker` instances on one node |
| `src/ingestion/platforms/base.py` | `PlatformAdapter` ABC + registry |
| `src/ingestion/platforms/tiktok.py` | TikTok adapter (refactor existing code) |
| `src/ingestion/platforms/youtube.py` | YouTube skeleton |
| `src/ingestion/platforms/facebook.py` | Facebook skeleton |
| `src/pipeline/video_analyzer.py` | CPU scene change + motion detection |
| `src/engine/llm_budget.py` | Daily LLM call budget tracker |
| `src/jobs/backup_daily.py` | SQLite + clips directory snapshot |
| `config/grafana/dashboard.json` | Grafana dashboard export |
| `config/orchestrator.json` | Node capacity, heartbeat interval |

### 3.4 Implementation sub-phases

| Sub-phase | Scope | Est. |
|---|---|---|
| **3a** | Observability — metrics, health endpoints, Grafana dashboard, structured logging | 1 wk |
| **3c** | Worker pool — `OrchestratorService`, `WorkerNode`, refactor `StreamManager` | 1.5 wk |
| **3b** | Platform adapters — ABC, TikTok refactor, YouTube/FB skeleton | 1 wk |
| **3d** | Video analysis CPU — `VideoAnalyzer`, aggregator weights | 1 wk |
| **3e** | Cost optimization — LLM budget, selective audio processing | 0.5 wk |
| **3f** | Backup & DR — daily snapshot, stream recovery | 0.5 wk |

---

## 4. Component Specifications

### 4.1 MetricsCollector (Phase 3a)

Uses `prometheus_client` library.

```python
# src/observability/metrics.py

class MetricsCollector:
    """Singleton metrics registry. Thread-safe."""

    # Counters
    streams_started_total: Counter      # labels: platform
    streams_stopped_total: Counter      # labels: platform, reason
    highlights_created_total: Counter   # labels: type (DRAFT|FINAL)
    llm_calls_total: Counter            # labels: gate (boundary|overlap), status (ok|fallback|budget_exceeded)
    pipeline_errors_total: Counter      # labels: stage

    # Gauges
    streams_active: Gauge               # labels: platform, node_id
    worker_node_healthy: Gauge          # labels: node_id

    # Histograms
    pipeline_chunk_duration_sec: Histogram
    stt_transcribe_duration_sec: Histogram
    clip_generate_duration_sec: Histogram

    def observe_chunk(self, duration_sec: float, stream_id: str) -> None: ...
    def inc_highlight(self, highlight_type: str) -> None: ...
    def set_streams_active(self, count: int, platform: str, node_id: str) -> None: ...
```

**Endpoints:**

| Path | Description |
|---|---|
| `GET /metrics` | Prometheus text exposition format |
| `GET /api/health` | `{"status": "ok"}` — process alive |
| `GET /api/health/ready` | `{"status": "ok", "db": true, "nodes": [...]}` — DB reachable + all nodes heartbeat < 60s |

**Grafana dashboard** (`config/grafana/dashboard.json`):
- Panel: Active streams by platform
- Panel: Pipeline chunk p50/p95 latency
- Panel: Highlights created rate (DRAFT vs FINAL)
- Panel: LLM calls + fallback rate
- Panel: STT latency
- Panel: Worker node health

**Structured logging:** Add `stream_id`, `platform`, `node_id` to log context via `logging.LoggerAdapter` in `StreamWorker` and `OrchestratorService`.

**Metric call-site map:**

| Metric | Caller | When |
|---|---|---|
| `streams_started_total` | `OrchestratorService.start_stream` | After worker thread starts |
| `streams_stopped_total` | `OrchestratorService.stop_stream` | After join completes |
| `streams_active` | `OrchestratorService` heartbeat | Every 30s + on start/stop |
| `highlights_created_total` | `HighlightProcessor` / DB insert | DRAFT or FINAL insert |
| `llm_calls_total` | `LLMGate` (all entry points) | Every call incl. editor `force=True` |
| `pipeline_errors_total` | `StreamWorker.run` except block | Uncaught stage errors |
| `pipeline_chunk_duration_sec` | `StreamWorker` | End of each `process_chunk` |
| `stt_transcribe_duration_sec` | `STTWorker` | After transcribe |
| `clip_generate_duration_sec` | `ClipGenerator` | After draft/final gen |
| `worker_node_healthy` | Heartbeat daemon | Every 30s |

---

### 4.2 OrchestratorService (Phase 3c)

Replaces direct use of `StreamManager` in API. `StreamManager` becomes a thin deprecated wrapper delegating to `OrchestratorService`.

#### 4.2.1 StreamRegistry

In-memory index synced with SQLite `streams` table. Not a separate process.

```python
class StreamRegistry:
    def register(self, info: StreamInfo) -> None: ...
    def get(self, stream_id: str) -> Optional[StreamInfo]: ...
    def update_status(self, stream_id: str, status: str, **kwargs) -> None: ...
    def list_active(self) -> List[StreamInfo]: ...
    def list_interrupted(self) -> List[StreamInfo]: ...  # status == INTERRUPTED
    def sync_from_db(self) -> None: ...  # called on init
```

#### 4.2.2 OrchestratorService

```python
@dataclass
class StreamInfo:
    stream_id: str
    platform: str
    url: str
    node_id: str
    started_at: float
    status: str  # RUNNING | STOPPING | STOPPED | ERROR | INTERRUPTED

WorkerFactory = Callable[..., StreamWorker]  # signature extended in 3b

class OrchestratorService:
    HEARTBEAT_INTERVAL_SEC = 30

    def __init__(
        self,
        db_path: str = "base_live.db",
        output_dir: str = "output/clips",
        max_streams_per_node: int = 5,
        worker_factory: Optional[WorkerFactory] = None,
        metrics: Optional[MetricsCollector] = None,
    ):
        # Starts daemon heartbeat thread on init
        ...

    def start_stream(self, url: str, stream_id: str, platform: str = "tiktok") -> StreamInfo: ...
    def stop_stream(self, stream_id: str, reason: str = "user_request") -> None: ...
    def list_streams(self) -> List[dict]: ...
    def list_interrupted(self) -> List[dict]: ...
    def recover_streams(self) -> List[str]: ...
    def get_node_health(self) -> List[dict]: ...
    def shutdown(self) -> None: ...  # stop heartbeat, stop all streams
```

**WorkerNode** (`src/ingestion/worker_node.py`):

```python
@dataclass
class _StreamEntry:
    worker: StreamWorker
    thread: threading.Thread

class WorkerNode:
    node_id: str = "node-0"

    def assign_stream(self, stream_id: str, worker: StreamWorker) -> None:
        """Create daemon thread targeting worker.run(), store in _streams."""

    def remove_stream(self, stream_id: str) -> StreamWorker:
        """Call worker.stop(), thread.join(timeout=5), pop entry."""

    def list_stream_ids(self) -> List[str]: ...
    def heartbeat(self) -> dict:
        # {node_id, stream_count, last_heartbeat_ts, healthy: True}
```

**Thread ownership:** `WorkerNode.assign_stream()` creates and starts the daemon thread (same pattern as current `StreamManager`). `OrchestratorService` delegates to `WorkerNode`; does not manage threads directly.

**Heartbeat daemon:** `OrchestratorService` starts a background thread on init that every `HEARTBEAT_INTERVAL_SEC` (30s, from `config/orchestrator.json`):
1. Calls `WorkerNode.heartbeat()`
2. Updates `worker_node_healthy` gauge
3. Updates `streams_active` gauge per platform

Readiness (`/api/health/ready`) fails if any node `last_heartbeat_ts` > 60s ago.

**3c interim contract (before 3b):**
- `platform` field accepted on API but **validated as `"tiktok"` only**; other values → HTTP 501
- `WorkerFactory` unchanged: `(url, stream_id) -> StreamWorker` with hardcoded TikTok ingestion
- `platform` persisted to `streams` table and metrics labels
- **3b checkpoint:** extend factory to `(url, stream_id, platform, adapter)`; wire `PlatformRegistry`

**Capacity rules:**
- `max_streams_per_node` default **5** (up from Phase 2's 3)
- Single `WorkerNode` on default deployment
- `CapacityError` → HTTP 429; `StreamAlreadyRunningError` → HTTP 409

**`streams` table lifecycle:**

| Event | DB `status` | Other fields |
|---|---|---|
| `start_stream` success | `RUNNING` | `node_id`, `started_at`, `platform`, `url` |
| `stop_stream` (user) | `STOPPED` | `ended_at` |
| Worker crash / max reconnect exceeded | `ERROR` | `ended_at` |
| App init `recover_streams()` | `RUNNING` → `INTERRUPTED` | — |

**Stream recovery (`recover_streams`):**
1. On Orchestrator init, `StreamRegistry.sync_from_db()`
2. Rows with `status = 'RUNNING'` → update to `INTERRUPTED`
3. Return interrupted stream IDs; exposed via `GET /api/streams/interrupted`
4. No auto-restart — editor uses `POST /api/streams/start`

**SQLite `streams` table** (migration in `database.py`):

```sql
CREATE TABLE IF NOT EXISTS streams (
  stream_id    TEXT PRIMARY KEY,
  platform     TEXT NOT NULL DEFAULT 'tiktok',
  url          TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'IDLE',
  node_id      TEXT,
  started_at   REAL,
  ended_at     REAL,
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**`GET /api/streams` response schema:**

```json
[
  {
    "stream_id": "s1",
    "platform": "tiktok",
    "url": "https://...",
    "node_id": "node-0",
    "status": "RUNNING",
    "uptime_sec": 342.5,
    "running": true
  }
]
```

`running` kept as deprecated alias: `running = (status == "RUNNING")` for backward compatibility with Phase 2d dashboard.

`StreamManager` deprecation: thin wrapper delegating to `OrchestratorService` for one release.

---

### 4.3 PlatformAdapter (Phase 3b)

Uses `Protocol` for ingestion components so skeleton adapters need not return concrete TikTok classes.

```python
# src/ingestion/platforms/base.py

class RecorderProtocol(Protocol):
    is_running: bool
    video_path: str
    def start(self) -> None: ...
    def stop(self) -> None: ...

class ChatCollectorProtocol(Protocol):
    is_running: bool
    def start(self) -> None: ...
    def stop(self) -> None: ...

class PlatformAdapter(ABC):
    platform_id: str
    default_chat_lag: float

    @abstractmethod
    def extract_username(self, url: str) -> str: ...

    @abstractmethod
    def create_recorder(self, url: str, audio_buffer: AudioRingBuffer, **kwargs) -> RecorderProtocol: ...

    @abstractmethod
    def create_chat_collector(self, url: str, chat_buffer: ChatBuffer, **kwargs) -> ChatCollectorProtocol: ...

    def is_available(self) -> bool:
        return True

class PlatformNotImplementedError(Exception):
    """Raised when a skeleton adapter is invoked."""

class PlatformRegistry:
    def register(self, adapter: PlatformAdapter) -> None: ...
    def get(self, platform_id: str) -> PlatformAdapter: ...
    def list_platforms(self) -> List[dict]:  # {id, available, default_chat_lag}
```

**TikTokAdapter** — returns concrete `StreamRecorder` + `ChatCollector`; `is_available() = True`.

**YouTubeAdapter / FacebookAdapter** — `is_available() = False`; `create_*` raises `PlatformNotImplementedError`. Listed in `GET /api/platforms`.

**StreamWorker changes (3b):**
- Constructor accepts `platform: str` and `adapter: PlatformAdapter`
- `adapter.create_recorder()` / `create_chat_collector()` replace direct instantiation
- `ChatLagCompensator(default_lag=adapter.default_chat_lag)`

**New API:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/platforms` | `{id, available, default_chat_lag}` per platform |

---

### 4.4 VideoAnalyzer (Phase 3d)

CPU-only, no GPU. Uses OpenCV (`cv2`) if available; graceful degrade if not installed.

```python
class VideoAnalyzer:
    SAMPLE_INTERVAL_SEC = 2.0   # 1 frame per 2 seconds
    SCENE_CHANGE_THRESHOLD = 0.35  # normalized histogram diff

    def __init__(self, enabled: bool = True): ...

    def sample_frame(self, video_path: str, pts: float) -> Optional[np.ndarray]:
        """Seek to pts in rolling mp4 via FFmpeg pipe or cv2.VideoCapture."""

    def analyze(self, frame: np.ndarray, prev_frame: Optional[np.ndarray]) -> dict:
        """
        Returns:
          scene_change_score: float 0–1 (histogram diff vs prev_frame)
          motion_score: float 0–1 (mean absolute pixel diff vs prev_frame)
        """
```

**SignalSnapshot extensions:**

```python
@dataclass
class SignalSnapshot:
    # ... existing fields ...
    video_scene_change: float = 0.0
    video_motion: float = 0.0
```

**Aggregator weight changes:**

```python
WEIGHTS = {
    "energy": 0.22,
    "laughter": 0.18,
    "chat_volume": 0.14,
    "speaking_rate": 0.13,
    "pitch": 0.09,
    "emoji_dominant": 0.09,
    "overlap": 0.05,
    "video_scene_change": 0.05,   # NEW
    "video_motion": 0.05,         # NEW
}
# Weights sum to 1.0; re-normalize if video disabled
```

**Integration in `StreamWorker` (not MasterPipeline):**

```python
# StreamWorker.__init__
self.video_analyzer = VideoAnalyzer()
self._prev_video_frame = None
self._quiet_streak = 0

# Inside run() loop, before process_chunk:
video_signals = {"video_scene_change": 0.0, "video_motion": 0.0}
if self.video_analyzer.enabled and self._quiet_streak < 3:
    frame = self.video_analyzer.sample_frame(clip_source, self._pts)
    if frame is not None:
        video_signals = self.video_analyzer.analyze(frame, self._prev_video_frame)
        self._prev_video_frame = frame

self.pipeline.process_chunk(..., video_signals=video_signals)
```

`MasterPipeline.process_chunk()` accepts optional `video_signals: dict` and copies values onto `SignalSnapshot`.

**Aggregator re-normalization:** Extend `_effective_weights()` to zero-out disabled components and redistribute:
- `stt_enabled=False` → zero `speaking_rate` (existing)
- `video_enabled=False` → zero `video_scene_change`, `video_motion`
- If both disabled, redistribute across remaining components proportionally

**Selective processing tie-in (3e):** `StreamWorker` increments `_quiet_streak` when `audio_energy < NOISE_FLOOR`; skip `sample_frame` when streak ≥ 3.

---

### 4.5 LLMBudgetTracker (Phase 3e)

```python
class LLMBudgetTracker:
    DEFAULT_DAILY_CAP = 100  # calls per day

    def __init__(self, daily_cap: int = 100, state_path: str = "config/llm_budget.json"): ...

    def can_call(self) -> bool: ...
    def record_call(self, gate: str, status: str) -> None: ...
    def remaining(self) -> int: ...
    def reset_if_new_day(self) -> None: ...
```

**Integration in `LLMGate` (all entry points):**
- Before any API call (including editor `force=True` via `/api/highlights/{id}/llm-analyze`): `if not budget_tracker.can_call(): return None`
- Editor-triggered calls use `gate="editor"` label; **count against same daily cap** (no exemption)
- After call: `budget_tracker.record_call(gate, "ok"|"fallback"|"error"|"budget_exceeded")`
- Expose `llm_budget_remaining` gauge in Prometheus

**Selective audio processing** in `MasterPipeline` (per-stream `_quiet_streak` on pipeline instance):
```python
NOISE_FLOOR = 0.02
_skip_video_count = 0

if audio_res["energy"] < NOISE_FLOOR:
    _quiet_streak += 1
else:
    _quiet_streak = 0

run_video = _quiet_streak < 3
run_full_dsp = _quiet_streak < 5  # skip pitch/laughter after 5 quiet chunks
```

---

### 4.6 Backup & Recovery (Phase 3f)

```python
# src/jobs/backup_daily.py

def run_backup(
    db_path: str = "base_live.db",
    clips_dir: str = "output/clips",
    backup_root: str = "backups",
    retain_days: int = 7,
) -> str:
    """
    1. Create backups/YYYY-MM-DD/ directory
    2. Copy base_live.db → backup dir
    3. Copy output/clips/ tree (or hardlink if same filesystem)
    4. Write manifest.json {timestamp, db_size, clip_count}
    5. Delete backup dirs older than retain_days
  Returns backup directory path.
    """
```

**CLI:** `python -m src.jobs.backup_daily`

**Recovery workflow (manual):**
1. Stop all streams
2. Replace `base_live.db` from backup
3. Restore `output/clips/` from backup
4. Restart API — `recover_streams()` marks interrupted streams
5. Editor re-starts streams manually

**Cron suggestion (documented, not automated):** Run backup daily at 03:00 local time.

---

## 5. API Changes Summary

| Method | Path | Change |
|---|---|---|
| `GET` | `/metrics` | **New** — Prometheus |
| `GET` | `/api/health` | **New** — liveness |
| `GET` | `/api/health/ready` | **New** — readiness |
| `GET` | `/api/platforms` | **New** — platform list + availability |
| `POST` | `/api/streams/start` | **Extended** — `platform` field (default `tiktok`) |
| `GET` | `/api/streams` | **Extended** — `platform`, `node_id`, `uptime_sec`, `status`; `running` alias kept |
| `GET` | `/api/streams/interrupted` | **New** — streams with `status=INTERRUPTED` after crash recovery |
| `GET` | `/api/highlights` | Unchanged |

**Dashboard UI (minimal Phase 3):**
- Header status dot reflects `/api/health/ready`
- Stream start form (future): platform dropdown from `/api/platforms`
- No full Grafana embed in Phase 3 — link to Grafana URL in README

---

## 6. Error Handling

| Failure | Behavior |
|---|---|
| Prometheus client import fails | `/metrics` returns 503; rest of app works |
| OpenCV not installed | `VideoAnalyzer` disabled; video signals = 0 |
| Platform skeleton requested | HTTP 501 `Platform not available` |
| Worker node at capacity | HTTP 429 |
| Duplicate stream_id | HTTP 409 |
| LLM budget exceeded | `LLMGate` returns None; rule-based boundary kept |
| Backup disk full | Log ERROR; skip backup; alert via log |
| Stream crash mid-run | Orchestrator marks `status=ERROR`; metrics `pipeline_errors_total` |
| Node heartbeat stale (>60s) | `/api/health/ready` returns 503 |

**Principle:** No observability or backup failure crashes ingestion. Video analysis failure degrades to audio-only signals.

---

## 7. Testing Strategy

**Target:** +30–35 new tests → **~146–151 total** (116 Phase 2 baseline + Phase 3)

| Module | Test focus |
|---|---|
| `MetricsCollector` | counter increment, histogram observe, `/metrics` endpoint returns text |
| `health` | `/api/health` 200, `/api/health/ready` 503 when heartbeat stale |
| `OrchestratorService` | start/stop, capacity 5, duplicate, recovery marks INTERRUPTED, thread join |
| `WorkerNode` | assign/remove, heartbeat, max capacity, daemon thread lifecycle |
| `StreamRegistry` | register, update_status, sync_from_db |
| `PlatformRegistry` | TikTok available, YouTube/FB not available |
| `TikTokAdapter` | URL parsing, creates recorder/collector |
| `YouTubeAdapter` | raises `PlatformNotImplementedError` |
| `VideoAnalyzer` | scene change on synthetic frames, motion score, disabled mode |
| `LLMBudgetTracker` | cap enforcement, daily reset, editor `force=True` counts |
| `backup_daily` | creates backup dir, manifest, retention prune |
| `orchestrator.json` | config loading, heartbeat interval |
| Integration | Stream start increments metrics; video signals in pipeline smoke |

**Fixtures:**
- `synthetic_video_frames` — numpy arrays with known diff in `tests/conftest.py`
- `mock_orchestrator` — fake worker factory for API tests

---

## 8. Out of Scope (Phase 4+)

| Item | Phase |
|---|---|
| PostgreSQL migration | Phase 4 |
| Redis / Kafka message queue | Phase 4 |
| YouTube / Facebook production ingestion | Phase 4 |
| Multi-VM worker pool + auto-scaling | Phase 4 |
| 10+ stream load test | Phase 4 |
| GPU video analysis | Phase 4 |
| Text overlay for partial context clips | Phase 4 |
| Grafana alerting rules (Slack/email) | Phase 4 (optional add-on) |
| Embedded Grafana in dashboard | Phase 4 |

---

## 9. Dependencies

| Package | Purpose | Required |
|---|---|---|
| `prometheus_client` | Metrics export | Yes (3a) |
| `opencv-python-headless` | Video frame analysis | Optional (degrades gracefully) |

Add to `requirements.txt`:
```
prometheus_client>=0.20.0
opencv-python-headless>=4.9.0  # optional, video analysis
```

---

## 10. Success Criteria

1. `GET /metrics` exposes stream count, pipeline latency, highlight rate
2. Grafana dashboard JSON importable and shows live data
3. `OrchestratorService` manages 5 streams on single `WorkerNode`
4. TikTok ingestion works identically via `TikTokAdapter` (no regression)
5. `GET /api/platforms` lists tiktok (available), youtube/facebook (unavailable)
6. `VideoAnalyzer` produces non-zero scene_change on synthetic test frames
7. `LLMBudgetTracker` blocks LLM calls after daily cap
8. `backup_daily` creates dated backup with manifest
9. `recover_streams()` marks interrupted streams after simulated crash
10. All existing Phase 2 tests pass; **+30–35** new Phase 3 tests pass (~146–151 total)

---

## 11. File Map

| File | Action | Sub-phase |
|---|---|---|
| `src/observability/metrics.py` | Create | 3a |
| `src/observability/health.py` | Create | 3a |
| `src/observability/__init__.py` | Create | 3a |
| `config/grafana/dashboard.json` | Create | 3a |
| `src/ingestion/orchestrator.py` | Create | 3c |
| `src/ingestion/worker_node.py` | Create | 3c |
| `src/ingestion/stream_manager.py` | Modify → thin wrapper | 3c |
| `src/ingestion/stream_worker.py` | Modify — platform adapter (3b), VideoAnalyzer (3d) | 3b, 3d |
| `src/ingestion/platforms/base.py` | Create | 3b |
| `src/ingestion/platforms/tiktok.py` | Create | 3b |
| `src/ingestion/platforms/youtube.py` | Create | 3b |
| `src/ingestion/platforms/facebook.py` | Create | 3b |
| `src/pipeline/video_analyzer.py` | Create | 3d |
| `src/engine/llm_budget.py` | Create | 3e |
| `src/engine/llm_gate.py` | Modify — budget check | 3e |
| `src/engine/pipeline.py` | Modify — video signals, selective processing | 3d, 3e |
| `src/engine/aggregator.py` | Modify — video weights | 3d |
| `src/core/models.py` | Modify — SignalSnapshot video fields | 3d |
| `src/db/database.py` | Modify — `streams` table | 3c |
| `src/api/main.py` | Modify — health, metrics, platforms endpoints | 3a, 3c, 3b |
| `src/jobs/backup_daily.py` | Create | 3f |
| `config/orchestrator.json` | Create | 3c |
| `requirements.txt` | Modify | 3a |
| `tests/observability/test_metrics.py` | Create | 3a |
| `tests/observability/test_health.py` | Create | 3a |
| `tests/ingestion/test_orchestrator.py` | Create | 3c |
| `tests/ingestion/test_worker_node.py` | Create | 3c |
| `tests/ingestion/test_platform_adapters.py` | Create | 3b |
| `tests/pipeline/test_video_analyzer.py` | Create | 3d |
| `tests/engine/test_llm_budget.py` | Create | 3e |
| `tests/jobs/test_backup_daily.py` | Create | 3f |
| `tests/api/test_routes.py` | Modify — health, platforms, orchestrator | 3a–3c |
| `docs/superpowers/plans/2026-06-17-livestream-highlight-mvp-plan.md` | Modify — Phase 3 summary | final |

---

## 12. Environment Setup

```bash
# Required for Phase 3a
pip install prometheus_client

# Optional for Phase 3d video analysis
pip install opencv-python-headless

# Grafana (optional, local)
# Import config/grafana/dashboard.json
# Point Prometheus scrape to http://localhost:8000/metrics

# Daily jobs
python -m src.jobs.feedback_daily   # existing Phase 2
python -m src.jobs.backup_daily     # new Phase 3
```
