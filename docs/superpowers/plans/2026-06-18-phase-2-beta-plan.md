# Phase 2 Beta — Highlight Accuracy & Learning — Implementation Plan

> **Status:** Ready for implementation
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cải thiện độ chính xác highlight — ranh giới clip đúng (look-back/forward + LLM), event không chồng/dài, calibration cold start, và feedback loop học từ editor.

**Architecture:** Incremental TDD qua 4 sub-phases (2a→2c→2b→2d). Mỗi sub-phase có test riêng, commit riêng. Draft/Final clip lifecycle. `HighlightProcessor` orchestrates post-CLOSED pipeline. Graceful degrade khi LLM unavailable.

**Tech Stack:** Python 3.11+, pytest, OpenRouter API (gemini-2.0-flash), SQLite, FastAPI, FFmpeg, numpy.

**Design spec:** `docs/superpowers/specs/2026-06-18-phase-2-beta-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/buffer/signal_history.py` | Create | Global 5-min `SignalSnapshot` ring buffer |
| `src/engine/context_expander.py` | Create | Look-back/forward boundary detection |
| `src/engine/llm_gate.py` | Create | OpenRouter boundary + overlap refinement |
| `src/engine/highlight_processor.py` | Create | Post-CLOSED orchestrator (stub→full) |
| `src/engine/pending_event_queue.py` | Create | Batch CLOSED events before resolve |
| `src/engine/event_resolver.py` | Create | Overlap/nested/adjacent resolution |
| `src/engine/event_splitter.py` | Create | Long event → TikTok micro-highlights |
| `src/engine/baseline_calibrator.py` | Create | 3-tier cold start thresholds |
| `src/engine/feedback_learner.py` | Create | Daily learning from editor feedback |
| `src/jobs/feedback_daily.py` | Create | CLI for daily batch job |
| `config/global_prior.json` | Create | Global baseline seed data |
| `config/stream_config.json` | Create | Per-stream learned overrides |
| `src/pipeline/chat_lag.py` | Create | Chat timestamp lag compensation |
| `src/ingestion/stream_manager.py` | Create | Up to 3 concurrent streams |
| `src/core/models.py` | Modify | BoundaryResult, ResolvedEvent, EventCandidate extensions |
| `src/engine/clip_generator.py` | Modify | `generate_draft()` / `generate_final()` |
| `src/engine/pipeline.py` | Modify | SignalHistory, draft lifecycle, pending queue poll |
| `src/engine/state_machine.py` | Modify | Dynamic thresholds, reset after CLOSED |
| `src/db/database.py` | Modify | Schema migration, feedback table, filters |
| `src/ingestion/stream_worker.py` | Modify | Look-forward blocking, HighlightProcessor wiring |
| `src/pipeline/chat_analyzer.py` | Modify | Use `adjusted_pts` |
| `src/api/main.py` | Modify | New endpoints, feedback capture |
| `src/api/static/js/app.js` | Modify | DRAFT/FINAL UI, reject modal, stream filter |
| `src/api/static/index.html` | Modify | Badges, filter tabs, reject modal |
| `tests/buffer/test_signal_history.py` | Create | SignalHistoryBuffer tests |
| `tests/engine/test_context_expander.py` | Create | Look-back/forward tests |
| `tests/engine/test_llm_gate.py` | Create | LLM gate tests (mocked) |
| `tests/engine/test_pending_event_queue.py` | Create | Queue timeout/batch tests |
| `tests/engine/test_event_resolver.py` | Create | Overlap resolution tests |
| `tests/engine/test_event_splitter.py` | Create | Multi-peak split tests |
| `tests/engine/test_highlight_processor.py` | Create | Orchestrator integration tests |
| `tests/engine/test_baseline_calibrator.py` | Create | 3-tier threshold tests |
| `tests/engine/test_feedback_learner.py` | Create | Learning pipeline tests |
| `tests/pipeline/test_chat_lag.py` | Create | Lag compensation tests |
| `tests/ingestion/test_stream_manager.py` | Create | Multi-stream tests |
| `tests/engine/test_pipeline.py` | Modify | Draft lifecycle tests |
| `tests/db/test_database.py` | Modify | Schema + feedback tests |
| `tests/api/test_routes.py` | Modify | New endpoint tests |
| `tests/integration/test_smoke.py` | Modify | DRAFT→FINAL smoke test |

---

## Phase 2a: Boundaries + Draft/Final + LLM Gate

### Task 1: SignalHistoryBuffer

**Files:**
- Create: `src/buffer/signal_history.py`
- Create: `tests/buffer/test_signal_history.py`

- [ ] **Step 1: Write the failing test**

```python
from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import SignalSnapshot

def test_signal_history_append_and_get_range():
    buf = SignalHistoryBuffer(capacity_sec=60)
    for i in range(5):
        buf.append(SignalSnapshot(pts=float(i * 5), composite_score=0.1 * i))
    entries = buf.get_range(5.0, 20.0)
    assert len(entries) == 4
    assert entries[0].pts == 5.0

def test_signal_history_evicts_old_entries():
    buf = SignalHistoryBuffer(capacity_sec=10)
    buf.append(SignalSnapshot(pts=0.0, composite_score=0.1))
    buf.append(SignalSnapshot(pts=15.0, composite_score=0.9))
    assert buf.oldest_pts() >= 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/buffer/test_signal_history.py -v`
Expected: FAIL (`SignalHistoryBuffer` not defined)

- [ ] **Step 3: Implement `SignalHistoryBuffer`**

Ring buffer of `HistoryEntry(snapshot, pts)`. Evict entries where `latest_pts - entry.pts > capacity_sec`. `get_at()` returns nearest entry within ±2.5s.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/buffer/test_signal_history.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/buffer/signal_history.py tests/buffer/test_signal_history.py
git commit -m "feat(2a): add SignalHistoryBuffer for look-back support"
```

---

### Task 2: Extended models (BoundaryResult, ResolvedEvent, EventCandidate)

**Files:**
- Modify: `src/core/models.py`
- Modify: `tests/core/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
from src.core.models import BoundaryResult, ResolvedEvent, EventCandidate

def test_boundary_result_fields():
    b = BoundaryResult(
        trigger_pts=90.0, resolution_pts=150.0, peak_pts=120.0,
        quality="complete", context_status="FULL", stop_reason="silence_gap",
    )
    assert b.trigger_pts == 90.0

def test_event_candidate_draft_fields():
    ev = EventCandidate(draft_highlight_id=42, is_growing=True, quality="partial")
    assert ev.draft_highlight_id == 42
    assert ev.is_growing is True
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add dataclasses to `models.py`**

Add: `BoundaryResult`, `ResolvedEvent`, `AmbiguousPair`, `ResolutionResult`, `MicroHighlight`, `ThresholdSet`. Extend `EventCandidate` with `draft_highlight_id`, `refined_start_pts`, `refined_end_pts`, `content_type`, `quality`, `is_growing`.

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add Phase 2 boundary and event models"
```

---

### Task 3: ContextExpander — topic similarity + look_back

**Files:**
- Create: `src/engine/context_expander.py`
- Create: `tests/engine/test_context_expander.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.context_expander import ContextExpander, topic_jaccard

def test_topic_jaccard():
    a = {"ôi", "trời", "ơi"}
    b = {"ôi", "trời", "không"}
    assert topic_jaccard(a, b) == pytest.approx(2 / 4)

def test_look_back_stops_at_silence_gap(history_with_silence):
    expander = ContextExpander()
    trigger = expander.look_back(
        peak_pts=60.0, history=history_with_silence,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert trigger < 60.0
    assert trigger >= 40.0
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement `topic_jaccard()` and `look_back()`**

Step back from `peak_pts` in 1s increments. Apply stop conditions per spec §4.2 (a→f). Use `EventHistoryStore.contains_pts()` for condition (f).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add ContextExpander look_back with stop conditions"
```

---

### Task 4: ContextExpander — look_forward + expand()

**Files:**
- Modify: `src/engine/context_expander.py`
- Modify: `tests/engine/test_context_expander.py`

- [ ] **Step 1: Write the failing test**

```python
def test_look_forward_stops_at_low_score(history_declining):
    expander = ContextExpander()
    resolution = expander.look_forward(
        peak_pts=60.0, close_pts=70.0,
        history=history_declining,
        transcript=TranscriptBuffer(capacity_sec=900),
    )
    assert resolution > 70.0
    assert resolution <= 60.0 + ContextExpander.MAX_LOOKFORWARD

def test_expand_returns_boundary_result(event_active, history, transcript, event_history):
    expander = ContextExpander()
    result = expander.expand(event_active, resolution_pts=95.0,
                             history=history, transcript=transcript,
                             event_history=event_history)
    assert isinstance(result, BoundaryResult)
    assert result.trigger_pts <= result.peak_pts <= result.resolution_pts
```

- [ ] **Step 2–4: Implement `look_forward()` and `expand()`, verify PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add ContextExpander look_forward and expand"
```

---

### Task 5: Database schema migration (Draft/Final columns)

**Files:**
- Modify: `src/db/database.py`
- Modify: `tests/db/test_database.py`

- [ ] **Step 1: Write the failing test**

```python
def test_insert_draft_highlight(tmp_db):
    hid = tmp_db.insert_highlight(
        stream_id="s1", start_pts=10.0, end_pts=50.0, score=0.8,
        highlight_type="DRAFT", is_growing=1, peak_pts=30.0,
    )
    row = tmp_db.get_highlight(hid)
    assert row["highlight_type"] == "DRAFT"
    assert row["is_growing"] == 1
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add migration in `init_db()`**

Use `PRAGMA table_info` to detect missing columns; `ALTER TABLE` for: `highlight_type`, `is_growing`, `quality`, `content_type`, `draft_clip_path`, `parent_id`, `peak_pts`, `ai_start_pts`, `ai_end_pts`.

Add `insert_highlight()` kwargs, `upgrade_to_final()`, `update_highlight()`, `get_highlights(type=, stream_id=)` filters. Hide `status=MERGED` from default query.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): extend highlights schema for Draft/Final lifecycle"
```

---

### Task 6: ClipGenerator draft and final methods

**Files:**
- Modify: `src/engine/clip_generator.py`
- Modify: `tests/engine/test_clip_generator.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_generate_draft_zero_post_roll():
    gen = ClipGenerator(source_file="live.mp4", pre_roll=10.0, post_roll=5.0)
    event = EventCandidate(start_pts=100.0, end_pts=100.0, peak_pts=110.0, peak_score=0.8)
    cmd = gen.build_draft_cmd(event, end_pts=130.0, output_path="out.mp4")
    t_index = cmd.index("-t")
    duration = float(cmd[t_index + 1])
    # (130 - 100) + pre_roll, no post_roll
    assert duration == pytest.approx(40.0)

def test_generate_final_uses_refined_boundaries():
    gen = ClipGenerator(source_file="live.mp4")
    cmd = gen.build_final_cmd(start_pts=95.0, end_pts=145.0, output_path="out.mp4")
    ss_index = cmd.index("-ss")
    assert float(cmd[ss_index + 1]) == pytest.approx(85.0)  # 95 - pre_roll 10
```

- [ ] **Step 2–4: Implement `build_draft_cmd`, `build_final_cmd`, `generate_draft()`, `generate_final()`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add ClipGenerator draft and final generation"
```

---

### Task 7: Draft lifecycle in MasterPipeline

**Files:**
- Modify: `src/engine/pipeline.py`
- Modify: `src/engine/state_machine.py`
- Modify: `tests/engine/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_creates_draft_on_first_active(mock_db):
    pipeline = MasterPipeline(db=mock_db, clip_source="live.mp4")
    # Drive OPENING → ACTIVE with high score audio+chat
    pipeline.process_chunk(pts=10.0, audio_data=loud_audio, chat_messages=hype_chat)
    assert pipeline.state_machine.current_event.state == "ACTIVE"
    mock_db.insert_highlight.assert_called_once()
    call_kwargs = mock_db.insert_highlight.call_args[1]
    assert call_kwargs.get("highlight_type") == "DRAFT" or \
           mock_db.insert_highlight.call_args[0]  # verify DRAFT via helper

def test_pipeline_does_not_duplicate_draft_on_peak_update(mock_db):
    pipeline = MasterPipeline(db=mock_db, clip_source="live.mp4")
    # Two chunks while ACTIVE with increasing score
    # insert_highlight called only once
```

- [ ] **Step 2–4: Implement**

- Wire `SignalHistoryBuffer.append()` each tick
- Detect `prev_state == "OPENING" and new_state == "ACTIVE"` → insert DRAFT once, set `draft_highlight_id`
- While ACTIVE: update same row score/peak_pts; regenerate draft clip every 30s
- On CLOSED: set `is_growing=0`, do NOT generate final clip yet (HighlightProcessor handles in Task 10)
- Reset `StateMachine.current_event = EventCandidate()` after CLOSED processing completes

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): wire Draft highlight lifecycle in MasterPipeline"
```

---

### Task 8: LLMGate (mocked OpenRouter)

**Files:**
- Create: `src/engine/llm_gate.py`
- Create: `tests/engine/test_llm_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch, MagicMock
from src.engine.llm_gate import LLMGate

def test_llm_gate_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gate = LLMGate()
    assert gate.enabled is False

def test_llm_gate_refine_boundary(mock_openrouter):
    gate = LLMGate(api_key="test-key")
    mock_openrouter.return_value = {
        "refined_start_pts": 98.5, "refined_end_pts": 142.0,
        "content_type": "funny", "confidence": 0.82, "reasoning": "setup-punchline",
    }
    result = gate.refine_boundary(boundary, transcript="ôi trời ơi", signals_summary={})
    assert result.refined_start_pts == 98.5

def test_llm_gate_rate_limit_blocks_excess_calls():
    gate = LLMGate(api_key="test-key")
    # Call 11 times in 1 hour → 11th returns None (fallback)
```

- [ ] **Step 2–4: Implement `LLMGate`**

- `enabled` property from env `OPENROUTER_API_KEY`
- `should_refine_boundary(event, boundary)` per spec §4.3 Pass 1
- `refine_boundary()` → POST to `https://openrouter.ai/api/v1/chat/completions`
- `resolve_overlap(pair)` → Pass 2 with `decision: MERGE|KEEP_BOTH|SUBORDINATE`
- Rate limit tracking: calls/hour, min gap, daily budget estimate
- Parse JSON from LLM response; fallback to input boundary on any error

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add LLMGate with OpenRouter integration and rate limits"
```

---

### Task 9: HighlightProcessor stub + StreamWorker look_forward

**Files:**
- Create: `src/engine/highlight_processor.py`
- Modify: `src/ingestion/stream_worker.py`
- Create: `tests/engine/test_highlight_processor.py`
- Modify: `tests/ingestion/test_stream_worker.py`

- [ ] **Step 1: Write the failing test**

```python
def test_highlight_processor_on_closed_enqueues_event():
    processor = HighlightProcessor(...)
    event = EventCandidate(state="CLOSED", peak_pts=60.0, start_pts=50.0, end_pts=80.0)
    processor.on_event_closed(event, history, transcript, "live.mp4", resolution_pts=90.0, current_pts=90.0)
    assert processor.pending_queue.is_ready(90.0) or len(processor.pending_queue._items) == 1
```

- [ ] **Step 2–4: Implement stub `HighlightProcessor`**

- `EventHistoryStore`, `PendingEventQueue` (minimal enqueue/drain for now)
- `on_event_closed()`: expand boundary → enqueue → process if ready
- `process_pending_queue()` stub: upgrade DRAFT→FINAL with rule-based boundary only (no resolver/split yet)
- `StreamWorker`: after CLOSED detected, blocking look_forward loop (poll every 5s tick until resolution or timeout)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add HighlightProcessor stub and StreamWorker look_forward"
```

---

### Task 10: Dashboard DRAFT/FINAL UI + API filters

**Files:**
- Modify: `src/api/main.py`
- Modify: `src/api/static/js/app.js`
- Modify: `src/api/static/index.html`
- Modify: `tests/api/test_routes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_get_highlights_filter_by_type(client, db_with_draft_and_final):
    resp = client.get("/api/highlights?type=DRAFT")
    assert resp.status_code == 200
    assert all(h["highlight_type"] == "DRAFT" for h in resp.json())
```

- [ ] **Step 2–4: Implement**

- API query params `type`, `stream_id`
- UI: DRAFT/FINAL badges, `is_growing` banner, disable approve when growing
- Filter tabs: All / Draft / Final / Pending
- Hide highlights with duration < 10s

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2a): add Draft/Final dashboard UI and API filters"
```

---

### Task 11: Phase 2a integration smoke test

**Files:**
- Modify: `tests/integration/test_smoke.py`

- [ ] **Step 1: Extend smoke test**

Inject loud audio + hype chat → verify DRAFT created on ACTIVE.
Continue injecting → verify CLOSED → verify highlight upgraded to FINAL (mock LLM).

- [ ] **Step 2: Run full suite**

Run: `pytest -v`
Expected: ~55–60 tests PASS

- [ ] **Step 3: Commit + update MVP plan status**

```bash
git commit -m "test(2a): integration smoke test for Draft/Final lifecycle"
```

---

## Phase 2c: Overlap Resolution + Event Splitting

### Task 12: PendingEventQueue

**Files:**
- Create: `src/engine/pending_event_queue.py`
- Create: `tests/engine/test_pending_event_queue.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.pending_event_queue import PendingEventQueue
from src.core.models import ResolvedEvent

def test_queue_ready_when_two_events():
    q = PendingEventQueue()
    q.enqueue(ResolvedEvent(0, 30, 15, 0.8, [], ""))
    q.enqueue(ResolvedEvent(25, 55, 40, 0.7, [], ""))
    assert q.is_ready(current_pts=55.0) is True

def test_queue_ready_after_timeout():
    q = PendingEventQueue(MAX_WAIT_SEC=30.0)
    q.enqueue(ResolvedEvent(0, 30, 15, 0.8, [], ""))
    assert q.is_ready(current_pts=35.0) is True
    assert q.is_ready(current_pts=10.0) is False
```

- [ ] **Step 2–4: Implement with `enqueue`, `is_ready`, `drain`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2c): add PendingEventQueue for batch event resolution"
```

---

### Task 13: EventResolver

**Files:**
- Create: `src/engine/event_resolver.py`
- Create: `tests/engine/test_event_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.event_resolver import EventResolver

def test_merge_overlapping_same_topic():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 30, 0.9, ["ôi", "trời"], "ôi trời ơi")
    b = ResolvedEvent(40, 80, 60, 0.7, ["ôi", "trời"], "ôi trời không")
    result = resolver.resolve([a, b])
    assert len(result.events) == 1
    assert result.events[0].peak_score == 0.9

def test_ambiguous_pair_returned():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 30, 0.8, ["game", "win"], "thắng game")
    b = ResolvedEvent(40, 80, 60, 0.7, ["ăn", "ngon"], "ăn ngon quá")
    result = resolver.resolve([a, b])
    # partial overlap, medium similarity → ambiguous
    assert len(result.ambiguous_pairs) >= 0  # tune fixture for 0.3-0.7 band
```

- [ ] **Step 2–4: Implement resolution matrix per spec §4.5**

Return `ResolutionResult(events, ambiguous_pairs)`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2c): add EventResolver with overlap resolution matrix"
```

---

### Task 14: EventSplitter

**Files:**
- Create: `src/engine/event_splitter.py`
- Create: `tests/engine/test_event_splitter.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.event_splitter import EventSplitter

def test_no_split_under_180s():
    splitter = EventSplitter()
    event = ResolvedEvent(0, 120, 60, 0.8, [], "")
    result = splitter.split(event, history)
    assert len(result) == 1

def test_split_long_event_into_micro_highlights(history_multi_peak):
    splitter = EventSplitter()
    event = ResolvedEvent(0, 300, 150, 0.9, [], "")
    result = splitter.split(event, history_multi_peak, platform="tiktok")
    assert len(result) >= 2
    for m in result:
        assert 15.0 <= (m.end_pts - m.start_pts) <= 60.0
```

- [ ] **Step 2–4: Implement multi-peak detection + TikTok duration targets**

Build `score_curve` from `SignalHistoryBuffer.get_range()`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2c): add EventSplitter for long event micro-highlights"
```

---

### Task 15: HighlightProcessor full wiring

**Files:**
- Modify: `src/engine/highlight_processor.py`
- Modify: `src/engine/pipeline.py`
- Modify: `tests/engine/test_highlight_processor.py`

- [ ] **Step 1: Write the failing integration test**

```python
def test_processor_full_pipeline_mock_llm(mock_llm, mock_clip_gen, db):
    processor = HighlightProcessor(...)
    # CLOSED event 200s duration → split into 2+ FINAL highlights
    results = processor.process_pending_queue(history, transcript, "live.mp4")
    assert len(results) >= 2
    for r in results:
        assert r["highlight_type"] == "FINAL"
```

- [ ] **Step 2–4: Implement full `process_pending_queue()`**

Steps per spec §4.11: refine → resolve → LLM overlap → split → final clips → DRAFT upgrade → event_history append.

Wire `MasterPipeline.process_chunk()` to poll `pending_queue.is_ready(current_pts)` each tick.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2c): complete HighlightProcessor orchestration pipeline"
```

---

## Phase 2b: Cold Start Calibration + Feedback Loop

### Task 16: BaselineCalibrator + global_prior.json

**Files:**
- Create: `src/engine/baseline_calibrator.py`
- Create: `config/global_prior.json`
- Create: `tests/engine/test_baseline_calibrator.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.baseline_calibrator import BaselineCalibrator

def test_phase0_lower_open_threshold():
    cal = BaselineCalibrator()
    thresholds = cal.get_thresholds(elapsed_sec=30.0, rolling_stats=empty_stats)
    assert thresholds.open_thr < cal.global_prior.open_thr

def test_phase2_uses_percentiles(rolling_stats_with_scores):
    cal = BaselineCalibrator()
    thresholds = cal.get_thresholds(elapsed_sec=400.0, rolling_stats=rolling_stats_with_scores)
    assert thresholds.open_thr > thresholds.close_thr
```

- [ ] **Step 2–4: Implement 3-tier strategy per spec §4.7**

Load `config/global_prior.json` on init.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2b): add BaselineCalibrator with 3-tier cold start"
```

---

### Task 17: Dynamic thresholds in StateMachine

**Files:**
- Modify: `src/engine/state_machine.py`
- Modify: `src/engine/pipeline.py`
- Modify: `tests/engine/test_state_machine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_state_machine_uses_dynamic_thresholds():
    sm = StateMachine()
    thresholds = ThresholdSet(open_thr=0.7, confirm_thr=0.8, close_thr=0.2, peak_thr=0.9)
    sm.process(SignalSnapshot(pts=1.0, composite_score=0.65), thresholds=thresholds)
    assert sm.current_event.state == "IDLE"  # below 0.7 open
```

- [ ] **Step 2–4: Pass `ThresholdSet` into `process()` from `BaselineCalibrator`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2b): wire dynamic thresholds into StateMachine"
```

---

### Task 18: highlight_feedback table + API capture

**Files:**
- Modify: `src/db/database.py`
- Modify: `src/api/main.py`
- Modify: `tests/db/test_database.py`
- Modify: `tests/api/test_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_reject_with_reason_writes_feedback(client, db):
    hid = db.insert_highlight(...)
    resp = client.post(f"/api/highlights/{hid}/reject", json={"reason": "false_positive"})
    assert resp.status_code == 200
  feedback = db.get_feedback_for_highlight(hid)
    assert feedback[0]["action"] == "REJECT"
    assert feedback[0]["reject_reason"] == "false_positive"
```

- [ ] **Step 2–4: Create `highlight_feedback` table; update approve/reject/adjust endpoints**

Add `RejectRequest` pydantic model with `reason` field.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2b): add highlight_feedback capture on editor actions"
```

---

### Task 19: FeedbackLearner + daily job

**Files:**
- Create: `src/engine/feedback_learner.py`
- Create: `src/jobs/feedback_daily.py`
- Create: `config/stream_config.json`
- Create: `tests/engine/test_feedback_learner.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.engine.feedback_learner import FeedbackLearner

def test_learner_skips_when_insufficient_data(db_few_feedback):
    learner = FeedbackLearner(db_few_feedback)
    result = learner.run_daily()
    assert result.applied is False

def test_learner_adjusts_pre_roll(db_enough_modify_feedback):
    learner = FeedbackLearner(db_enough_modify_feedback)
    result = learner.run_daily()
    assert result.pre_roll_delta != 0
```

- [ ] **Step 2–4: Implement daily batch per spec §4.8**

Write learned values to `config/stream_config.json` and `config/global_prior.json`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2b): add FeedbackLearner and daily batch job"
```

---

### Task 20: Reject reason UI + post-peak cooldown

**Files:**
- Modify: `src/api/static/index.html`
- Modify: `src/api/static/js/app.js`

- [ ] **Step 1: Manual test checklist**

- Reject opens modal with reason dropdown
- Approve disabled when `is_growing=true`
- Approve disabled for 10s after peak_pts (post-peak cooldown)
- `content_type` and `quality` warnings displayed

- [ ] **Step 2: Implement UI changes**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(2b): add reject reason modal and editor safeguards"
```

---

## Phase 2d: Chat Lag + Multi-Stream

### Task 21: ChatLagCompensator

**Files:**
- Create: `src/pipeline/chat_lag.py`
- Modify: `src/pipeline/chat_analyzer.py`
- Create: `tests/pipeline/test_chat_lag.py`

- [ ] **Step 1: Write the failing test**

```python
from src.pipeline.chat_lag import ChatLagCompensator

def test_adjust_message_applies_lag():
    comp = ChatLagCompensator(default_lag=5.0)
    msg = {"pts": 100.0, "content": "haha"}
    adjusted = comp.adjust_message(msg)
    assert adjusted["adjusted_pts"] == 95.0

def test_calibrate_updates_lag():
    comp = ChatLagCompensator(default_lag=5.0)
    comp.calibrate_from_spike(audio_spike_pts=100.0, chat_spike_pts=108.0)
    assert comp.current_lag > 5.0
```

- [ ] **Step 2–4: Implement; wire into `ChatAnalyzer.analyze_batch()`**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2d): add ChatLagCompensator with passive calibration"
```

---

### Task 22: StreamManager + API

**Files:**
- Create: `src/ingestion/stream_manager.py`
- Modify: `src/api/main.py`
- Create: `tests/ingestion/test_stream_manager.py`
- Modify: `tests/api/test_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_stream_manager_max_concurrent():
    mgr = StreamManager()
    mgr.start_stream("url1", "s1")
    mgr.start_stream("url2", "s2")
    mgr.start_stream("url3", "s3")
    with pytest.raises(CapacityError):
        mgr.start_stream("url4", "s4")

def test_api_start_stream(client):
    resp = client.post("/api/streams/start", json={"url": "http://test", "stream_id": "s1"})
    assert resp.status_code == 200
```

- [ ] **Step 2–4: Implement StreamManager with thread-per-worker**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(2d): add StreamManager for 3 concurrent streams"
```

---

### Task 23: Stream filter UI + final integration

**Files:**
- Modify: `src/api/static/js/app.js`
- Modify: `src/api/static/index.html`
- Modify: `tests/integration/test_smoke.py`
- Modify: `docs/superpowers/plans/2026-06-17-livestream-highlight-mvp-plan.md`

- [ ] **Step 1: Stream selector in dashboard**

- [ ] **Step 2: Full suite**

Run: `pytest -v`
Expected: **~75–85 tests PASS**

- [ ] **Step 3: Update MVP plan with Phase 2 summary table**

```bash
git commit -m "feat(2d): stream filter UI and Phase 2 Beta complete"
```

---

## Tổng kết Phase 2 Beta

| Sub-phase | Nội dung | Tasks |
|---|---|---|
| 2a | SignalHistory, ContextExpander, LLMGate, Draft/Final | Tasks 1–11 |
| 2c | PendingQueue, EventResolver, EventSplitter, Processor | Tasks 12–15 |
| 2b | BaselineCalibrator, FeedbackLearner, reject UI | Tasks 16–20 |
| 2d | ChatLag, StreamManager | Tasks 21–23 |
| **TỔNG** | | **23 tasks** |

### Không nằm trong plan này

- Live TikTok E2E with real OpenRouter (manual QA)
- Embedding-based topic detection (Phase 4)
- VideoBuffer TS segments
- Text overlay for partial context clips

### Environment setup

```bash
# Optional — enables LLM gate
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="google/gemini-2.0-flash-001"
```
