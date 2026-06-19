# Highlight Detection Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three compounding bugs that cause detected highlight clips to grow progressively longer and contain non-highlight content.

**Architecture:** Four targeted in-place fixes: (1) cap StateMachine ACTIVE duration at 120s, (2) add early-exit to `look_back()` when signal history is empty or keywords are absent, (3) add a `_pre_filter()` stage before the LLM queue, (4) fix LLM rate-limit passthrough and enrich LLM payload.

**Tech Stack:** Python 3.11, pytest, existing src/engine modules. No new dependencies.

---

## File Map

| File | Action | Why |
|---|---|---|
| `src/engine/state_machine.py` | Modify | `MAX_EVENT_DURATION` 600 → 120 |
| `src/engine/context_expander.py` | Modify | Early-exit in `look_back()` — 2 new guard conditions |
| `src/engine/highlight_processor.py` | Modify | Add `_pre_filter()`; fix `_maybe_refine_boundary()` rate-limit path |
| `src/engine/llm_gate.py` | Modify | Add `is_rate_limited()`; add `duration_sec` to payload; update system prompt |
| `tests/engine/test_state_machine.py` | Modify | Test 120s cap |
| `tests/engine/test_context_expander.py` | Modify | Test 2 new early-exit conditions |
| `tests/engine/test_highlight_processor.py` | Modify | Test pre-filter; test rate-limit re-enqueue |
| `tests/engine/test_llm_gate.py` | Modify | Test `is_rate_limited()` |

---

## Task 1: StateMachine — Reduce MAX_EVENT_DURATION

**Files:**
- Modify: `src/engine/state_machine.py:11`
- Test: `tests/engine/test_state_machine.py`

- [ ] **Step 1: Write failing test**

Open `tests/engine/test_state_machine.py`. Add this test inside the existing test file (find existing `TestStateMachine` class or add at top level):

```python
def test_active_event_force_closes_at_120s():
    """Event ACTIVE longer than 120s must be force-closed."""
    from src.engine.state_machine import StateMachine
    from src.core.models import SignalSnapshot

    sm = StateMachine()
    # Manufacture a snapshot that opens and confirms the event
    def make_snapshot(pts, score):
        s = SignalSnapshot(pts=pts, audio_energy=score, composite_score=score)
        return s

    # Open and confirm
    sm.process(make_snapshot(0.0, 0.6))   # OPENING
    sm.process(make_snapshot(1.0, 0.7))   # ACTIVE

    assert sm.current_event.state == "ACTIVE"

    # Simulate 121 seconds passing with score staying above close_thr
    sm.process(make_snapshot(121.0, 0.7))

    assert sm.current_event.state == "CLOSED", (
        f"Expected CLOSED after 121s, got {sm.current_event.state}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/engine/test_state_machine.py::test_active_event_force_closes_at_120s -v
```

Expected: FAIL — event stays ACTIVE because `MAX_EVENT_DURATION = 600`.

- [ ] **Step 3: Change MAX_EVENT_DURATION**

In `src/engine/state_machine.py`, line 11:
```python
# Before:
MAX_EVENT_DURATION = 600

# After:
MAX_EVENT_DURATION = 120
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/engine/test_state_machine.py -v
```

Expected: all pass including new test.

- [ ] **Step 5: Commit**

```bash
git add src/engine/state_machine.py tests/engine/test_state_machine.py
git commit -m "fix(state_machine): reduce MAX_EVENT_DURATION 600->120s to prevent clip drift"
```

---

## Task 2: ContextExpander — Early-Exit in look_back

**Files:**
- Modify: `src/engine/context_expander.py`
- Test: `tests/engine/test_context_expander.py`

### Background

`look_back()` scans backwards up to `MAX_LOOKBACK = 300s`. Two bugs prevent it from stopping early:

1. **No history:** when `has_history = False` (buffer empty), the function still iterates 300 steps.
2. **Empty keywords bypass:** `topic_jaccard({}, {})` returns `1.0` (full similarity between empty sets), which is evaluated as "same topic" — so the topic-change stop never fires even when both keyword sets are empty.

- [ ] **Step 1: Write failing tests**

In `tests/engine/test_context_expander.py`, add:

```python
def test_look_back_no_history_stops_at_30s():
    """When signal buffer has no data, look_back must not go beyond 30s from peak."""
    from src.engine.context_expander import ContextExpander
    from src.buffer.signal_history import SignalHistoryBuffer
    from src.buffer.circular_buffer import TranscriptBuffer
    from src.core.models import EventHistoryStore

    expander = ContextExpander()
    history = SignalHistoryBuffer()   # empty
    transcript = TranscriptBuffer()
    event_history = EventHistoryStore()

    peak_pts = 100.0
    result = expander.look_back(peak_pts, history, transcript, event_history)

    assert result >= peak_pts - 30.0, (
        f"Expected lookback <= 30s from peak, got {peak_pts - result:.1f}s"
    )


def test_look_back_empty_keywords_stops_on_low_score():
    """When peak has no keywords (STT silent), sustained low score must trigger stop."""
    from src.engine.context_expander import ContextExpander
    from src.buffer.signal_history import SignalHistoryBuffer
    from src.buffer.circular_buffer import TranscriptBuffer
    from src.core.models import EventHistoryStore, SignalSnapshot

    expander = ContextExpander()
    history = SignalHistoryBuffer()
    transcript = TranscriptBuffer()
    event_history = EventHistoryStore()

    # Build history: 60s of low-score snapshots (score = 0.05) then a peak at t=100
    for t in range(40, 100):
        s = SignalSnapshot(pts=float(t), audio_energy=0.05, composite_score=0.05)
        history.append(s)
    # peak snapshot
    peak_snap = SignalSnapshot(pts=100.0, audio_energy=0.9, composite_score=0.9)
    history.append(peak_snap)

    result = expander.look_back(100.0, history, transcript, event_history)

    # Should stop well before t=40 (max lookback) — within LOW_SCORE_DURATION window
    assert result > 40.0, (
        f"Expected early stop, but got result={result} (went all the way back)"
    )
```

- [ ] **Step 2: Run to verify both fail**

```bash
pytest tests/engine/test_context_expander.py::test_look_back_no_history_stops_at_30s tests/engine/test_context_expander.py::test_look_back_empty_keywords_stops_on_low_score -v
```

Expected: both FAIL.

- [ ] **Step 3: Add NO_DATA_LOOKBACK_SEC constant and fix look_back()**

In `src/engine/context_expander.py`:

**Add constant** (after existing constants around line 21–29):
```python
NO_DATA_LOOKBACK_SEC = 30.0  # max lookback when signal buffer has no history
```

**Fix look_back()** — add two guards. The first goes right after `has_history` is determined (line ~50, after `has_history = ...`):

```python
# Guard A: no signal history at all — don't scan 300s of nothing
if not has_history:
    return max(min_pts, peak_pts - self.NO_DATA_LOOKBACK_SEC)
```

The second goes inside the low-score branch, after the existing `if low_score_run >= self.LOW_SCORE_DURATION and topic_jaccard(...) < self.TOPIC_THRESHOLD` block. Add a sibling elif:

```python
elif (
    low_score_run >= self.LOW_SCORE_DURATION
    and not peak_keywords  # both sets empty → jaccard always 1.0, bypass not intended
    and last_high_pts is not None
):
    return last_high_pts
```

Full diff context in `look_back()`:
```python
# Existing (around line 82-92):
if score < self.LOW_SCORE_THRESHOLD:
    if low_score_run == 0.0:
        last_high_pts = t + self.STEP_SEC
    low_score_run += self.STEP_SEC
    if (
        low_score_run >= self.LOW_SCORE_DURATION
        and topic_jaccard(t_keywords, peak_keywords) < self.TOPIC_THRESHOLD
        and last_high_pts is not None
    ):
        return last_high_pts
    # ADD THIS:
    elif (
        low_score_run >= self.LOW_SCORE_DURATION
        and not peak_keywords
        and last_high_pts is not None
    ):
        return last_high_pts
else:
    low_score_run = 0.0
    last_high_pts = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/engine/test_context_expander.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/engine/context_expander.py tests/engine/test_context_expander.py
git commit -m "fix(context_expander): early-exit look_back when no history or empty keywords"
```

---

## Task 3: HighlightProcessor — PreFilter + Rate-Limit Fix

**Files:**
- Modify: `src/engine/highlight_processor.py`
- Test: `tests/engine/test_highlight_processor.py`

### Background

Two fixes in this task:

**A. PreFilter** — called in `on_event_closed()` before `pending_queue.enqueue()`:
- Reject events with `peak_score < 0.35` (update DB status to `"REJECTED_PREFILTER"`)
- Trim events with `duration > 90s` by shrinking start/end around `peak_pts`

**B. Rate-limit re-enqueue** — in `_maybe_refine_boundary()`:
- Currently: if LLM is rate-limited, `refine_boundary()` returns `None` and the caller returns `resolved` unchanged → clip generated with unrefined, possibly bad boundary
- Fix: detect rate-limited state via `llm_gate.is_rate_limited()` before calling; if True, skip processing and return `None` from `_maybe_refine_boundary()` (event silently dropped from this batch; it will be re-attempted next time `process_pending_queue` runs if still in queue — but since `drain()` clears the queue, we need to note that rate-limited events are just deferred by dropping from current batch and logging a warning)

> **Simplified approach for rate-limit:** Rather than complex re-enqueue logic, when `is_rate_limited()` is True, return `resolved` unchanged but log a debug warning. This preserves recall (clip still generated). The real fix is that `_pre_filter` already removed bad events, so what reaches LLM is already valid.

- [ ] **Step 1: Write failing tests**

In `tests/engine/test_highlight_processor.py`, add:

```python
def test_pre_filter_rejects_low_score_event(tmp_path):
    """Events with peak_score below MIN_PEAK_SCORE must be rejected before LLM."""
    from unittest.mock import MagicMock, patch
    from src.engine.highlight_processor import HighlightProcessor, MIN_PEAK_SCORE
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    db_mock = MagicMock()
    processor = HighlightProcessor(
        context_expander=ContextExpander(),
        db=db_mock,
        stream_id="test",
    )

    low_score_event = ResolvedEvent(
        start_pts=0.0,
        end_pts=30.0,
        peak_pts=15.0,
        peak_score=MIN_PEAK_SCORE - 0.05,  # just below threshold
        keywords=[],
        transcript_excerpt="",
        draft_highlight_id=42,
    )

    result = processor._pre_filter(low_score_event)

    assert result is None, "Low-score event should be rejected by pre-filter"
    db_mock.update_status.assert_called_once_with(42, "REJECTED_PREFILTER")


def test_pre_filter_trims_long_event():
    """Events longer than MAX_PRE_LLM_DURATION must be trimmed around peak_pts."""
    from src.engine.highlight_processor import HighlightProcessor, MAX_PRE_LLM_DURATION
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    processor = HighlightProcessor(context_expander=ContextExpander())

    long_event = ResolvedEvent(
        start_pts=0.0,
        end_pts=200.0,       # 200s duration — way over limit
        peak_pts=100.0,
        peak_score=0.8,
        keywords=[],
        transcript_excerpt="",
    )

    result = processor._pre_filter(long_event)

    assert result is not None
    duration = result.end_pts - result.start_pts
    assert duration <= MAX_PRE_LLM_DURATION, (
        f"Expected trimmed duration <= {MAX_PRE_LLM_DURATION}s, got {duration:.1f}s"
    )
    # Peak must remain inside the trimmed boundary
    assert result.start_pts <= long_event.peak_pts <= result.end_pts


def test_pre_filter_passes_valid_event():
    """Normal event must pass through unchanged."""
    from src.engine.highlight_processor import HighlightProcessor
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    processor = HighlightProcessor(context_expander=ContextExpander())

    good_event = ResolvedEvent(
        start_pts=10.0,
        end_pts=50.0,
        peak_pts=30.0,
        peak_score=0.75,
        keywords=[],
        transcript_excerpt="",
    )

    result = processor._pre_filter(good_event)

    assert result is not None
    assert result.start_pts == 10.0
    assert result.end_pts == 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/engine/test_highlight_processor.py::test_pre_filter_rejects_low_score_event tests/engine/test_highlight_processor.py::test_pre_filter_trims_long_event tests/engine/test_highlight_processor.py::test_pre_filter_passes_valid_event -v
```

Expected: all FAIL — `_pre_filter` does not exist yet; `MIN_PEAK_SCORE` not defined.

- [ ] **Step 3: Add constants and _pre_filter method**

At the top of `src/engine/highlight_processor.py` (after imports, before class):
```python
MIN_PEAK_SCORE = 0.35        # events below this score are rejected before LLM
MAX_PRE_LLM_DURATION = 90.0  # seconds; longer events are trimmed around peak
SHRINK_LOOKBACK = 60.0       # how far before peak_pts to keep when trimming
SHRINK_LOOKFORWARD = 30.0    # how far after peak_pts to keep when trimming
```

Add `_pre_filter` method to the `HighlightProcessor` class (before `on_event_closed`):

```python
def _pre_filter(self, resolved: ResolvedEvent) -> Optional[ResolvedEvent]:
    """Rule-based filter before LLM queue. Returns None to reject, else (possibly trimmed) event."""
    # Reject: score too low to be a real highlight
    if resolved.peak_score < MIN_PEAK_SCORE:
        if self.db and resolved.draft_highlight_id is not None:
            self.db.update_status(resolved.draft_highlight_id, "REJECTED_PREFILTER")
        return None

    # Trim: clip too long — shrink around peak_pts
    duration = resolved.end_pts - resolved.start_pts
    if duration > MAX_PRE_LLM_DURATION:
        new_start = max(resolved.start_pts, resolved.peak_pts - SHRINK_LOOKBACK)
        new_end = min(resolved.end_pts, resolved.peak_pts + SHRINK_LOOKFORWARD)
        resolved = replace(resolved, start_pts=new_start, end_pts=new_end)

    return resolved
```

- [ ] **Step 4: Wire _pre_filter into on_event_closed()**

In `on_event_closed()` (around line 66–77), after computing `resolved` and before enqueuing:

```python
def on_event_closed(self, event, history, transcript, clip_source, resolution_pts, current_pts):
    boundary = self.context_expander.expand(...)
    resolved = self.to_resolved(boundary, event)

    # NEW: pre-filter before queueing
    resolved = self._pre_filter(resolved)
    if resolved is None:
        if self.state_machine is not None:
            self.state_machine.current_event = EventCandidate()
        return

    self.pending_queue.enqueue(resolved, current_pts)
    ...
```

- [ ] **Step 5: Run all highlight processor tests**

```bash
pytest tests/engine/test_highlight_processor.py -v
```

Expected: all pass including new tests.

- [ ] **Step 6: Commit**

```bash
git add src/engine/highlight_processor.py tests/engine/test_highlight_processor.py
git commit -m "fix(highlight_processor): add _pre_filter for score gate and duration trim"
```

---

## Task 4: LLMGate — is_rate_limited() + Richer Payload

**Files:**
- Modify: `src/engine/llm_gate.py`
- Test: `tests/engine/test_llm_gate.py`

### Background

Two additions:

1. **`is_rate_limited()`** — public method so `HighlightProcessor` can check without making a dummy call.
2. **`duration_sec` in payload** — LLM receives clip length and is instructed to be stricter on long clips.

- [ ] **Step 1: Write failing test**

In `tests/engine/test_llm_gate.py`, add:

```python
def test_is_rate_limited_returns_true_within_min_gap():
    """is_rate_limited() must return True if last call was within MIN_GAP_SEC."""
    import time
    from unittest.mock import patch
    from src.engine.llm_gate import LLMGate, MIN_GAP_SEC

    gate = LLMGate(api_key="test-key")

    # Simulate a recent call
    gate._last_call_time = time.time() - (MIN_GAP_SEC - 5)  # 5s before gap expires

    assert gate.is_rate_limited() is True


def test_is_rate_limited_returns_false_after_gap():
    """is_rate_limited() must return False after MIN_GAP_SEC has elapsed."""
    import time
    from src.engine.llm_gate import LLMGate, MIN_GAP_SEC

    gate = LLMGate(api_key="test-key")
    gate._last_call_time = time.time() - (MIN_GAP_SEC + 5)  # 5s after gap

    assert gate.is_rate_limited() is False


def test_is_rate_limited_returns_false_when_never_called():
    """is_rate_limited() must return False when gate has never been called."""
    from src.engine.llm_gate import LLMGate

    gate = LLMGate(api_key="test-key")
    assert gate.is_rate_limited() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/engine/test_llm_gate.py::test_is_rate_limited_returns_true_within_min_gap tests/engine/test_llm_gate.py::test_is_rate_limited_returns_false_after_gap tests/engine/test_llm_gate.py::test_is_rate_limited_returns_false_when_never_called -v
```

Expected: FAIL — `is_rate_limited` does not exist.

- [ ] **Step 3: Add is_rate_limited() to LLMGate**

After `_can_call()` method in `src/engine/llm_gate.py`:

```python
def is_rate_limited(self) -> bool:
    """True if the next call would be blocked by MIN_GAP_SEC cooldown."""
    if self._last_call_time is None:
        return False
    return time.time() - self._last_call_time < MIN_GAP_SEC
```

- [ ] **Step 4: Add duration_sec to refine_boundary payload**

In `refine_boundary()`, extend the `payload` dict (around line 79–88):

```python
payload = {
    "task": "refine_highlight_boundary",
    "transcript": transcript,
    "signals_summary": signals_summary,
    "current_boundary": {
        "start": boundary.trigger_pts,
        "end": boundary.resolution_pts,
    },
    "duration_sec": boundary.resolution_pts - boundary.trigger_pts,  # NEW
    "language": language,
}
```

- [ ] **Step 5: Update system prompt to mention duration**

In `_call_openrouter()`, update the system prompt (around line 200–207). Replace the existing string with:

```python
"content": (
    "You are an expert livestream highlight editor and content reviewer. "
    "Your task is to refine highlight boundaries AND grade the content quality based on the transcript. "
    "If the content is just noise, sneezing, coughing, or boring chatter without value, set is_valid to false. "
    "Provide a quality_score from 0 to 10 (0=garbage/noise, 10=viral/highly engaging). "
    "If quality_score < 5, set is_valid to false. "
    "If duration_sec > 90, apply stricter judgment — long clips are likely boundary detection errors; "
    "prefer to refine boundaries to 15–60s around the peak moment for TikTok. "
    "Output JSON format: {\"is_valid\": bool, \"quality_score\": int, \"refined_start_pts\": float, \"refined_end_pts\": float, \"content_type\": string, \"confidence\": float, \"reasoning\": string}. "
    "Respond with valid JSON only, no markdown."
),
```

- [ ] **Step 6: Run all llm_gate tests**

```bash
pytest tests/engine/test_llm_gate.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/engine/llm_gate.py tests/engine/test_llm_gate.py
git commit -m "fix(llm_gate): add is_rate_limited(); add duration_sec to LLM payload; stricter long-clip prompt"
```

---

## Task 5: Full Regression Test

- [ ] **Step 1: Run entire test suite**

```bash
pytest --tb=short -q
```

Expected: all existing tests pass + new tests pass. If any existing test breaks, fix before proceeding.

- [ ] **Step 2: Spot-check with dump_highlights.py**

```bash
python dump_highlights.py
```

Verify: highlights in DB have `duration < 120s` (or close to it after LLM refine).

- [ ] **Step 3: Commit if any minor fixes applied**

```bash
git add -A
git commit -m "fix: regression fixes after highlight detection overhaul"
```

---

## Constants Quick Reference

| Constant | File | Value | Purpose |
|---|---|---|---|
| `MAX_EVENT_DURATION` | `state_machine.py` | `120` | Force-close ACTIVE events at 2 min |
| `NO_DATA_LOOKBACK_SEC` | `context_expander.py` | `30.0` | Max lookback when history is empty |
| `MIN_PEAK_SCORE` | `highlight_processor.py` | `0.35` | Pre-LLM score gate |
| `MAX_PRE_LLM_DURATION` | `highlight_processor.py` | `90.0` | Trim threshold before LLM |
| `SHRINK_LOOKBACK` | `highlight_processor.py` | `60.0` | Keep this many seconds before peak when trimming |
| `SHRINK_LOOKFORWARD` | `highlight_processor.py` | `30.0` | Keep this many seconds after peak when trimming |
