# Phase 3 — Production Readiness — Implementation Plan

> **Status:** Ready for implementation (plan review iteration 1 fixes applied)
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production-ready architecture — Prometheus observability, Orchestrator/WorkerNode pool (3–5 streams), platform adapter layer (TikTok prod + YT/FB skeleton), CPU video signals, LLM budget guardrails, daily backup.

**Architecture:** Incremental TDD qua 6 sub-phases (3a→3c→3b→3d→3e→3f). Observability first; worker pool before adapters. Video sampling owned by `StreamWorker`. Graceful degrade when OpenCV/Prometheus unavailable.

**Tech Stack:** Python 3.11+, pytest, prometheus_client, OpenCV (optional), SQLite, FastAPI, FFmpeg, numpy.

**Design spec:** `docs/superpowers/specs/2026-06-18-phase-3-production-design.md`

**Prerequisite:** Phase 2 Beta source present + **116/116 tests pass** before Task 1. If `src/engine/llm_gate.py` missing, restore Phase 2 first (Task 0).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/observability/metrics.py` | Create | Prometheus `MetricsCollector` singleton |
| `src/observability/health.py` | Create | Liveness/readiness checks |
| `src/observability/__init__.py` | Create | Package init |
| `config/grafana/dashboard.json` | Create | Grafana dashboard export |
| `config/orchestrator.json` | Create | Node capacity, heartbeat interval |
| `src/ingestion/stream_registry.py` | Create | In-memory stream index + DB sync |
| `src/ingestion/worker_node.py` | Create | Thread-per-stream on one node |
| `src/ingestion/orchestrator.py` | Create | Stream lifecycle, heartbeat daemon |
| `src/ingestion/stream_manager.py` | Modify | Thin wrapper → `OrchestratorService` |
| `src/ingestion/platforms/base.py` | Create | `PlatformAdapter` ABC + registry |
| `src/ingestion/platforms/tiktok.py` | Create | TikTok production adapter |
| `src/ingestion/platforms/youtube.py` | Create | YouTube skeleton |
| `src/ingestion/platforms/facebook.py` | Create | Facebook skeleton |
| `src/pipeline/video_analyzer.py` | Create | CPU scene change + motion |
| `src/engine/llm_budget.py` | Create | Daily LLM call cap |
| `src/jobs/backup_daily.py` | Create | SQLite + clips snapshot CLI |
| `src/core/models.py` | Modify | `video_scene_change`, `video_motion` on `SignalSnapshot` |
| `src/db/database.py` | Modify | `streams` table CRUD |
| `src/engine/aggregator.py` | Modify | Video weights + re-normalize |
| `src/engine/pipeline.py` | Modify | `video_signals` param, selective DSP |
| `src/engine/llm_gate.py` | Modify | Budget check all entry points |
| `src/ingestion/stream_worker.py` | Modify | Adapter injection, VideoAnalyzer |
| `src/api/main.py` | Modify | `/metrics`, health, platforms, orchestrator |
| `src/api/static/js/app.js` | Modify | Health status dot on header |
| `requirements.txt` | Modify | `prometheus_client`, optional opencv |
| `tests/observability/test_metrics.py` | Create | Metrics unit tests |
| `tests/observability/test_health.py` | Create | Health endpoint tests |
| `tests/ingestion/test_stream_registry.py` | Create | Registry + DB sync |
| `tests/ingestion/test_worker_node.py` | Create | Node capacity, threads |
| `tests/ingestion/test_orchestrator.py` | Create | Start/stop/recovery |
| `tests/ingestion/test_platform_adapters.py` | Create | TikTok + skeleton adapters |
| `tests/pipeline/test_video_analyzer.py` | Create | Scene change + motion |
| `tests/engine/test_llm_budget.py` | Create | Cap + daily reset |
| `tests/jobs/test_backup_daily.py` | Create | Backup + retention |
| `tests/api/test_routes.py` | Modify | Health, metrics, platforms, orchestrator |
| `src/engine/highlight_processor.py` | Modify | `highlights_created_total` metric |
| `src/pipeline/stt_worker.py` | Modify | `stt_transcribe_duration_sec` metric |
| `src/engine/clip_generator.py` | Modify | `clip_generate_duration_sec` metric |
| `src/observability/logging_context.py` | Create | `LoggerAdapter` with stream_id/platform/node_id |
| `config/llm_budget.json` | Create | Budget state seed |
| `src/ingestion/platforms/__init__.py` | Create | Package init |
| `tests/engine/test_llm_gate.py` | Create or Modify | Budget + gate tests |
| `docs/superpowers/plans/2026-06-17-livestream-highlight-mvp-plan.md` | Modify | Phase 3 summary |

---

## Task 0: Prerequisite gate (Phase 2 restore)

**Files:** Verify only — restore Phase 2 if missing.

- [ ] **Step 1: Verify Phase 2 modules exist**

```bash
for f in src/engine/llm_gate.py src/engine/highlight_processor.py src/engine/context_expander.py \
         src/engine/baseline_calibrator.py src/pipeline/chat_lag.py src/engine/feedback_learner.py; do
  test -f "$f" || echo "MISSING: $f"
done
```

Expected: no MISSING lines. If any missing, restore Phase 2 source (re-run Phase 2 plan or restore from git history) before continuing.

- [ ] **Step 2: Verify Phase 2 behavior**

| Check | How |
|---|---|
| Draft/Final lifecycle | `tests/integration/test_smoke.py::test_full_pipeline_draft_to_final_lifecycle` exists |
| `highlight_feedback` | `tests/api/test_routes.py` has reject/approve feedback tests |
| Dynamic thresholds | `tests/engine/test_baseline_calibrator.py` exists |

- [ ] **Step 3: Run full test suite**

```bash
./venv/Scripts/python.exe -m pytest -q
```

Expected: **116/116 PASS**. Do not start Task 1 until green.

---

## Phase 3a: Observability

### Task 1: Dependencies + MetricsCollector

**Files:**
- Modify: `requirements.txt`
- Create: `src/observability/__init__.py`
- Create: `src/observability/metrics.py`
- Create: `tests/observability/test_metrics.py`

- [ ] **Step 1: Add dependency**

Add to `requirements.txt`:
```
prometheus_client>=0.20.0
```

Run: `./venv/Scripts/pip.exe install prometheus_client`

- [ ] **Step 2: Write the failing test**

```python
# tests/observability/test_metrics.py
from src.observability.metrics import MetricsCollector

def test_metrics_collector_singleton():
    m1 = MetricsCollector.get_instance()
    m2 = MetricsCollector.get_instance()
    assert m1 is m2

def test_inc_streams_started():
    m = MetricsCollector.get_instance()
    before = m.streams_started_total.labels(platform="tiktok")._value.get()
    m.inc_stream_started("tiktok")
    after = m.streams_started_total.labels(platform="tiktok")._value.get()
    assert after == before + 1

def test_observe_chunk_histogram():
    m = MetricsCollector.get_instance()
    m.observe_chunk(1.5, "s1")
    # no exception = pass
```

- [ ] **Step 3: Implement `MetricsCollector`**

Singleton with counters/gauges/histograms per design §4.1. Methods: `get_instance()`, `inc_stream_started`, `inc_stream_stopped`, `inc_highlight`, `inc_llm_call`, `inc_pipeline_error`, `observe_chunk`, `observe_stt`, `observe_clip_gen`, `set_streams_active`, `set_node_healthy`, `export_text()`.

- [ ] **Step 4: Run tests**

```bash
./venv/Scripts/python.exe -m pytest tests/observability/test_metrics.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3a): add MetricsCollector with Prometheus metrics"
```

---

### Task 2: Health checks

**Files:**
- Create: `src/observability/health.py`
- Create: `tests/observability/test_health.py`

- [ ] **Step 1: Write the failing test**

```python
from src.observability.health import check_liveness, check_readiness

def test_liveness_always_ok():
    assert check_liveness() == {"status": "ok"}

def test_readiness_returns_not_ready_when_nodes_stale():
    nodes = [{"node_id": "node-0", "last_heartbeat_ts": 0.0, "healthy": False}]
    result = check_readiness(db_ok=True, nodes=nodes, max_stale_sec=60)
    assert result["ready"] is False
```

API must return **HTTP 503** when `ready` is False (Task 3).

- [ ] **Step 2–4: Implement; run tests**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3a): add liveness and readiness health checks"
```

---

### Task 3: API — `/metrics`, `/api/health`, `/api/health/ready`

**Files:**
- Modify: `src/api/main.py`
- Modify: `tests/api/test_routes.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_health_liveness(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "streams_active" in resp.text or "# HELP" in resp.text

def test_readiness_returns_503_when_not_ready(client):
    # override orchestrator to return stale nodes
    resp = client.get("/api/health/ready")
    # with healthy default: 200; with stale mock: 503
```

- [ ] **Step 2–4: Wire endpoints**

- `GET /metrics` → `MetricsCollector.export_text()`; return 503 if prometheus_client missing
- `GET /api/health` → `check_liveness()` — always 200
- `GET /api/health/ready` → return **503** when `check_readiness()["ready"] is False`; else 200

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3a): expose /metrics and health endpoints"
```

---

### Task 4: Grafana dashboard JSON

**Files:**
- Create: `config/grafana/dashboard.json`

- [ ] **Step 1: Create dashboard**

Panels per design §4.1: active streams, chunk latency p50/p95, highlights rate, LLM calls, STT latency, node health. Use Prometheus queries targeting metric names from Task 1.

- [ ] **Step 2: Validate JSON**

```bash
python -c "import json; json.load(open('config/grafana/dashboard.json'))"
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(3a): add Grafana dashboard JSON for BaseLive metrics"
```

---

### Task 4b: Structured logging context

**Files:**
- Create: `src/observability/logging_context.py`
- Modify: `src/ingestion/stream_worker.py`, `src/ingestion/orchestrator.py`

- [ ] **Step 1: Implement `stream_logger(name, stream_id, platform, node_id)`** returning `logging.LoggerAdapter`

- [ ] **Step 2: Replace bare `logger` in StreamWorker/Orchestrator** with contextual logger

- [ ] **Step 3: Smoke test** — caplog captures `stream_id` in log extra fields

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(3a): add structured logging context for stream and node"
```

---

## Phase 3c: Worker Pool + Orchestrator

### Task 5: `streams` table migration

**Files:**
- Modify: `src/db/database.py`
- Modify: `tests/db/test_database.py`

- [ ] **Step 1: Write failing test**

```python
def test_streams_table_crud(test_db):
    test_db.upsert_stream("s1", platform="tiktok", url="http://x", status="RUNNING", node_id="node-0", started_at=100.0)
    row = test_db.get_stream("s1")
    assert row["status"] == "RUNNING"
    test_db.update_stream_status("s1", "STOPPED", ended_at=200.0)
    assert test_db.get_stream("s1")["status"] == "STOPPED"
```

- [ ] **Step 2–4: Implement migration + CRUD**

Methods: `upsert_stream`, `get_stream`, `update_stream_status`, `list_streams_by_status`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3c): add streams table and CRUD methods"
```

---

### Task 6: StreamRegistry

**Files:**
- Create: `src/ingestion/stream_registry.py`
- Create: `tests/ingestion/test_stream_registry.py`

- [ ] **Step 1: Write failing test**

```python
from src.ingestion.stream_registry import StreamRegistry, StreamInfo

def test_register_and_list_active():
    reg = StreamRegistry()
    info = StreamInfo("s1", "tiktok", "http://x", "node-0", 100.0, "RUNNING")
    reg.register(info)
    assert len(reg.list_active()) == 1

def test_stream_registry_sync_from_db(test_db):
    test_db.upsert_stream("s1", platform="tiktok", url="http://x", status="RUNNING", node_id="node-0", started_at=100.0)
    reg = StreamRegistry(db=test_db)
    reg.sync_from_db()
    assert reg.get("s1").status == "RUNNING"
```

- [ ] **Step 2–5: Implement `sync_from_db()`; commit**

```bash
git commit -m "feat(3c): add StreamRegistry in-memory index"
```

---

### Task 7: WorkerNode

**Files:**
- Create: `src/ingestion/worker_node.py`
- Create: `tests/ingestion/test_worker_node.py`

- [ ] **Step 1: Write failing test**

Use fake worker with `run()` that sleeps until `stop()`:

```python
def test_worker_node_capacity():
    node = WorkerNode(node_id="node-0", max_streams=2)
    # assign 2 fake workers → OK
    # assign 3rd → CapacityError

def test_worker_node_heartbeat():
    node = WorkerNode(node_id="node-0", max_streams=5)
    hb = node.heartbeat()
    assert hb["node_id"] == "node-0"
    assert hb["healthy"] is True
```

- [ ] **Step 2–5: Implement thread lifecycle per design §4.2.2; commit**

```bash
git commit -m "feat(3c): add WorkerNode with thread-per-stream management"
```

---

### Task 8: OrchestratorService (core)

**Files:**
- Create: `src/ingestion/orchestrator.py`
- Create: `config/orchestrator.json`
- Create: `tests/ingestion/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
def test_orchestrator_start_stop(fake_factory, tmp_path):
    orch = OrchestratorService(db_path=":memory:", output_dir=str(tmp_path), worker_factory=fake_factory)
    orch.start_stream("http://test", "s1", platform="tiktok")
    assert "s1" in [s["stream_id"] for s in orch.list_streams()]
    orch.stop_stream("s1")
    assert orch.list_streams() == []

def test_orchestrator_capacity_5(fake_factory):
    orch = OrchestratorService(worker_factory=fake_factory, max_streams_per_node=5)
    for i in range(5):
        orch.start_stream(f"http://t{i}", f"s{i}")
    with pytest.raises(CapacityError):
        orch.start_stream("http://t6", "s6")

def test_orchestrator_rejects_non_tiktok_platform(fake_factory):
    orch = OrchestratorService(worker_factory=fake_factory)
    with pytest.raises(PlatformNotSupportedError):
        orch.start_stream("http://yt", "s1", platform="youtube")
```

**3c interim:** only `platform="tiktok"` allowed. **`WorkerFactory` stays `(url, stream_id) -> StreamWorker`** with hardcoded TikTok ingestion — no `PlatformAdapter` until Task 14.

- [ ] **Step 2–4: Implement**

- Load `config/orchestrator.json`: `{ "max_streams_per_node": 5, "heartbeat_interval_sec": 30 }`
- `WorkerNode` + `StreamRegistry` + DB sync on start/stop
- Heartbeat daemon thread on init — updates `worker_node_healthy` and `streams_active` gauges only (not `streams_started_total`; see Task 10)
- `recover_streams()` on init: `RUNNING` → `INTERRUPTED`
- Test: `test_recover_marks_interrupted`, `test_duplicate_stream_raises`, `test_loads_orchestrator_config`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3c): add OrchestratorService with heartbeat and recovery"
```

---

### Task 9: Refactor StreamManager + API orchestrator endpoints

**Files:**
- Modify: `src/ingestion/stream_manager.py`
- Modify: `src/api/main.py`
- Modify: `tests/api/test_routes.py`
- Modify: `tests/ingestion/test_stream_manager.py`

- [ ] **Step 1: StreamManager thin wrapper** — `StreamManager` delegates to injected `OrchestratorService` (deprecated alias, one release)

- [ ] **Step 2: Update API**

- App singleton: `_orchestrator = OrchestratorService()` (not raw `StreamManager`)
- `get_orchestrator()` dependency; keep `get_stream_manager()` as alias returning wrapper for backward compat
- `POST /api/streams/start` — optional `platform` (default `tiktok`); 501 for non-tiktok until Task 14
- `GET /api/streams` — extended schema with `running` alias
- `GET /api/streams/interrupted` — new endpoint
- `GET /api/health/ready` — uses `orchestrator.get_node_health()`; 503 when stale

- [ ] **Step 3: Add API error tests**

```python
def test_api_start_stream_409_duplicate(stream_client): ...
def test_api_start_stream_429_at_capacity(stream_client): ...
def test_api_start_stream_501_non_tiktok_platform(stream_client): ...
def test_api_health_ready_503_when_stale(stream_client): ...
```

- [ ] **Step 4: Run tests**

```bash
./venv/Scripts/python.exe -m pytest tests/ingestion/test_stream_manager.py tests/ingestion/test_orchestrator.py tests/api/test_routes.py -v
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3c): wire OrchestratorService to API; extend stream endpoints"
```

---

### Task 10: Metrics instrumentation — worker + downstream

**Files:**
- Modify: `src/ingestion/stream_worker.py`
- Modify: `src/engine/highlight_processor.py` (or DB insert hook)
- Modify: `src/pipeline/stt_worker.py`
- Modify: `src/engine/clip_generator.py`
- Modify: `src/ingestion/orchestrator.py` (start/stop counters only)

| Metric | Location |
|---|---|
| `streams_started_total` | `OrchestratorService.start_stream` |
| `streams_stopped_total` | `OrchestratorService.stop_stream` |
| `pipeline_chunk_duration_sec` | `StreamWorker` after `process_chunk` |
| `pipeline_errors_total` | `StreamWorker.run` except block |
| `highlights_created_total` | `HighlightProcessor` on DRAFT/FINAL insert |
| `stt_transcribe_duration_sec` | `STTWorker.transcribe_chunk` |
| `clip_generate_duration_sec` | `ClipGenerator.generate_draft/final` |

- [ ] **Step 1–3: Wire all call sites; add unit smoke tests per module**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(3c): wire full Prometheus metric call-site map"
```

---

### Task 10b: LLM + orchestrator gauge metrics (deferred to 3e)

Moved to Task 20 (`llm_calls_total`, `llm_budget_remaining`). Heartbeat gauges wired in Task 8.

---

## Phase 3b: Platform Adapters

### Task 11: PlatformAdapter base + registry

**Files:**
- Create: `src/ingestion/platforms/__init__.py`
- Create: `src/ingestion/platforms/base.py`
- Create: `tests/ingestion/test_platform_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
def test_registry_lists_platforms():
    reg = PlatformRegistry()
    reg.register(TikTokAdapter())
    reg.register(YouTubeAdapter())
    platforms = reg.list_platforms()
    ids = [p["id"] for p in platforms]
    assert "tiktok" in ids
    assert "youtube" in ids

def test_youtube_not_available():
    adapter = YouTubeAdapter()
    assert adapter.is_available() is False
    with pytest.raises(PlatformNotImplementedError):
        adapter.create_recorder("url", audio_buffer=MagicMock())
```

- [ ] **Step 2–5: Implement Protocol + ABC + registry; commit**

```bash
git commit -m "feat(3b): add PlatformAdapter base and registry"
```

---

### Task 12: TikTokAdapter

**Files:**
- Create: `src/ingestion/platforms/tiktok.py`
- Modify: `tests/ingestion/test_platform_adapters.py`

- [ ] **Step 1: Test URL parsing**

```python
def test_tiktok_extract_username():
    a = TikTokAdapter()
    assert a.extract_username("https://tiktok.com/@user/live") == "user"
    assert a.extract_username("user") == "user"
```

def test_tiktok_creates_recorder_and_collector():
    a = TikTokAdapter()
    recorder = a.create_recorder("http://x", audio_buffer=MagicMock())
    collector = a.create_chat_collector("http://x", chat_buffer=MagicMock())
    assert recorder is not None
    assert collector is not None
```

- [ ] **Step 2: Implement** — wrap `StreamRecorder` + `ChatCollector`; `default_chat_lag=5.0`

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(3b): add TikTokAdapter wrapping existing ingestion"
```

---

### Task 13: YouTube + Facebook skeleton adapters

**Files:**
- Create: `src/ingestion/platforms/youtube.py`
- Create: `src/ingestion/platforms/facebook.py`

- [ ] **Step 1: Tests** — `is_available() == False`, `create_*` raises `PlatformNotImplementedError`

- [ ] **Step 2: Implement skeletons**

- [ ] **Step 3: Register defaults in `PlatformRegistry` factory helper**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(3b): add YouTube and Facebook skeleton platform adapters"
```

---

### Task 14: StreamWorker adapter injection + API platforms

**Files:**
- Modify: `src/ingestion/stream_worker.py`
- Modify: `src/ingestion/orchestrator.py`
- Modify: `src/api/main.py`
- Modify: `tests/ingestion/test_stream_worker.py`
- Modify: `tests/api/test_routes.py`

- [ ] **Step 1: StreamWorker accepts `adapter: PlatformAdapter`**

Replace direct `StreamRecorder`/`ChatCollector` instantiation with `adapter.create_recorder()` / `create_chat_collector()`.

- [ ] **Step 2: Orchestrator worker factory**

```python
def _create_worker(url, stream_id, platform="tiktok"):
    adapter = platform_registry.get(platform)
    if not adapter.is_available():
        raise PlatformNotSupportedError(platform)
    ...
    return StreamWorker(url=url, username=adapter.extract_username(url), adapter=adapter, ...)
```

- [ ] **Step 3: `GET /api/platforms`**

- [ ] **Step 4: `POST /api/streams/start`** — allow platform param; return 501 for unavailable platforms

- [ ] **Step 5: Regression test** — existing `test_stream_worker_calls_pipeline_process_chunk` still passes

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(3b): wire PlatformAdapter into StreamWorker and API"
```

---

## Phase 3d: Video Analysis (CPU)

### Task 15: SignalSnapshot video fields

**Files:**
- Modify: `src/core/models.py`
- Modify: `tests/core/test_models.py`

- [ ] **Step 1: Test defaults**

```python
def test_signal_snapshot_video_fields_default_zero():
    s = SignalSnapshot(pts=0.0)
    assert s.video_scene_change == 0.0
    assert s.video_motion == 0.0
```

- [ ] **Step 2–4: Add fields; commit**

```bash
git commit -m "feat(3d): extend SignalSnapshot with video signal fields"
```

---

### Task 16: VideoAnalyzer

**Files:**
- Modify: `requirements.txt` (optional opencv)
- Create: `src/pipeline/video_analyzer.py`
- Create: `tests/pipeline/test_video_analyzer.py`
- Modify: `tests/conftest.py` — `synthetic_video_frames` fixture

- [ ] **Step 1: Write failing tests (no file I/O)**

```python
import numpy as np
from src.pipeline.video_analyzer import VideoAnalyzer

def test_analyze_detects_scene_change():
    va = VideoAnalyzer(enabled=True)
    frame_a = np.zeros((64, 64, 3), dtype=np.uint8)
    frame_b = np.ones((64, 64, 3), dtype=np.uint8) * 255
    r = va.analyze(frame_b, frame_a)
    assert r["video_scene_change"] > 0.3
    assert r["video_motion"] > 0.0

def test_analyze_no_prev_frame_returns_zeros():
    va = VideoAnalyzer(enabled=True)
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    r = va.analyze(frame, None)
    assert r["video_scene_change"] == 0.0

@patch("cv2.VideoCapture")
def test_sample_frame_returns_array(MockCap):
    va = VideoAnalyzer(enabled=True)
    mock_cap = MockCap.return_value
    mock_cap.read.return_value = (True, np.zeros((64, 64, 3), dtype=np.uint8))
    frame = va.sample_frame("/tmp/fake.mp4", pts=10.0)
    assert frame is not None
```

- [ ] **Step 2–4: Implement `sample_frame` (cv2 seek by pts) + `analyze`; `enabled=False` when cv2 missing**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3d): add CPU VideoAnalyzer with scene change and motion"
```

---

### Task 17: Pipeline + Aggregator video integration

**Files:**
- Modify: `src/engine/pipeline.py`
- Modify: `src/engine/aggregator.py`
- Modify: `tests/engine/test_aggregator.py`
- Modify: `tests/engine/test_pipeline.py`

- [ ] **Step 1: `process_chunk(..., video_signals=None)`**

Copy `video_scene_change` / `video_motion` onto `SignalSnapshot`.

- [ ] **Step 2: Aggregator weights** — add `video_scene_change`, `video_motion` at 0.05 each; extend `_effective_weights()` for `video_enabled=False`.

- [ ] **Step 3: Tests** — composite score changes when video signals non-zero

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(3d): wire video signals into pipeline and aggregator"
```

---

### Task 18: StreamWorker video sampling

**Files:**
- Modify: `src/ingestion/stream_worker.py`
- Modify: `tests/ingestion/test_stream_worker.py`

- [ ] **Step 1: Unit test with mocked VideoAnalyzer**

```python
@patch("src.ingestion.stream_worker.VideoAnalyzer")
def test_stream_worker_passes_video_signals_to_pipeline(MockVA, ...):
    MockVA.return_value.analyze.return_value = {"video_scene_change": 0.8, "video_motion": 0.5}
    # run one iteration; assert process_chunk called with video_signals
```

- [ ] **Step 2: Implement in StreamWorker**

- `VideoAnalyzer` in `__init__`; `_prev_video_frame`, `_quiet_streak` per worker
- Before `process_chunk`: if `_quiet_streak < 3` and analyzer enabled, call `sample_frame` + `analyze`
- Pass `video_signals` dict to `process_chunk`
- Update `_quiet_streak` from last chunk's `audio_energy` (read from pipeline or audio_dsp result)

**Note:** `MasterPipeline` maintains separate `_quiet_streak` for selective DSP (pitch/laughter skip when ≥ 5) — Task 20.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(3d): StreamWorker samples video frames and passes signals"
```

---

## Phase 3e: Cost Optimization

### Task 19: LLMBudgetTracker

**Files:**
- Create: `src/engine/llm_budget.py`
- Create: `config/llm_budget.json` (seed)
- Create: `tests/engine/test_llm_budget.py`

- [ ] **Step 1: Write failing tests**

```python
def test_budget_blocks_after_cap(tmp_path):
    tracker = LLMBudgetTracker(daily_cap=2, state_path=str(tmp_path / "budget.json"))
    assert tracker.can_call()
    tracker.record_call("boundary", "ok")
    tracker.record_call("boundary", "ok")
    assert not tracker.can_call()

def test_budget_resets_new_day(tmp_path):
    # mock date rollover
```

- [ ] **Step 2–5: Implement; commit**

```bash
git commit -m "feat(3e): add LLMBudgetTracker with daily call cap"
```

---

### Task 20: LLMGate + selective processing

**Files:**
- Modify: `src/engine/llm_gate.py`
- Modify: `src/engine/pipeline.py`
- Modify: `src/api/main.py` (editor llm-analyze uses budget)
- Modify: `tests/engine/test_llm_gate.py`

- [ ] **Step 1: Test budget blocks LLM call**

```python
def test_llm_gate_respects_budget(mock_budget):
    mock_budget.can_call.return_value = False
    result = gate.refine_boundary(...)
    assert result is None
```

def test_editor_llm_analyze_counts_against_budget(client, mock_budget_at_cap):
    resp = client.post("/api/highlights/1/llm-analyze")
    assert resp.status_code == 503  # budget exceeded
```

- [ ] **Step 2: Wire budget** — all `LLMGate` entry points including editor `force=True` with `gate="editor"`

- [ ] **Step 3: Selective DSP** — `_quiet_streak` on `MasterPipeline`; skip pitch/laughter when streak ≥ 5

- [ ] **Step 4: Expose `llm_calls_total` and `llm_budget_remaining` gauge** (Task 10b scope)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(3e): LLM budget guardrails and selective audio processing"
```

---

## Phase 3f: Backup + UI + Integration

### Task 21: backup_daily job

**Files:**
- Create: `src/jobs/backup_daily.py`
- Create: `tests/jobs/test_backup_daily.py`

- [ ] **Step 1: Write failing test**

```python
def test_backup_creates_manifest(tmp_path):
    db = tmp_path / "base_live.db"
    db.write_bytes(b"sqlite")
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "a.mp4").write_bytes(b"vid")
    out = run_backup(db_path=str(db), clips_dir=str(clips), backup_root=str(tmp_path / "backups"), retain_days=7)
    manifest = json.loads((Path(out) / "manifest.json").read_text())
def test_backup_retention_prunes_old(tmp_path):
    # create 2 dated backup dirs; retain_days=1; assert old removed
```

- [ ] **Step 2–5: Implement; commit**

```bash
git commit -m "feat(3f): add daily backup job for SQLite and clips"
```

---

### Task 22: Dashboard health status dot

**Files:**
- Modify: `src/api/static/js/app.js`
- Modify: `src/api/static/index.html` (if needed)

- [ ] **Step 1: Poll `/api/health/ready` on init + every 8s**

- Green dot when `status == "ok"`; amber/red when degraded

- [ ] **Step 2: Manual smoke** — start uvicorn, verify dot changes

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(3f): dashboard header reflects readiness health"
```

---

### Task 23: Full suite + MVP plan update

**Files:**
- Modify: `docs/superpowers/plans/2026-06-17-livestream-highlight-mvp-plan.md`

- [ ] **Step 1: Run full suite**

```bash
./venv/Scripts/python.exe -m pytest -v
```

Expected: **~146–151 tests PASS**

- [ ] **Step 2: Update MVP plan** — add Phase 3 summary table (3a–3f)

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(3f): Phase 3 Production complete — observability, orchestrator, adapters, video, backup"
```

---

## Tổng kết Phase 3

| Sub-phase | Nội dung | Tasks |
|---|---|---|
| Prereq | Phase 2 gate (expanded checklist) | Task 0 |
| 3a | MetricsCollector, health, `/metrics`, Grafana, structured logging | Tasks 1–4, 4b |
| 3c | streams table, StreamRegistry, WorkerNode, Orchestrator, API, metrics call sites | Tasks 5–10 |
| 3b | PlatformAdapter, TikTok/YT/FB, StreamWorker wiring | Tasks 11–14 |
| 3d | VideoAnalyzer (+sample_frame), pipeline, aggregator, StreamWorker | Tasks 15–18 |
| 3e | LLMBudgetTracker, selective DSP, `llm_calls_total` | Tasks 19–20 |
| 3f | backup_daily, dashboard health, MVP plan | Tasks 21–23 |
| **TỔNG** | | **25 tasks** (0–23 + 4b) |

### Không nằm trong plan này

- PostgreSQL / Redis / Kafka
- YouTube/Facebook production ingestion
- Multi-VM auto-scaling
- 10+ stream load test
- GPU video analysis
- Grafana Slack alerting
- Embedded Grafana in dashboard

### Test fixtures note

Define in `tests/conftest.py`:
- `synthetic_video_frames` — numpy arrays for VideoAnalyzer
- `fake_worker` / `fake_factory` — for orchestrator tests (pattern from `test_stream_manager.py`)
- `mock_orchestrator` — API test dependency override

### Environment setup

```bash
pip install prometheus_client
pip install opencv-python-headless  # optional

# Metrics
curl http://localhost:8000/metrics

# Daily jobs
python -m src.jobs.feedback_daily
python -m src.jobs.backup_daily
```

### pytest command (Windows)

```bash
./venv/Scripts/python.exe -m pytest -v
```
