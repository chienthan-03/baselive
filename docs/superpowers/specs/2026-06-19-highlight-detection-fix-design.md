# Highlight Detection Fix — Technical Design

> **Version:** 1.0
> **Date:** 2026-06-19
> **Status:** Approved
> **Parent spec:** `docs/superpowers/specs/2026-06-18-phase-3-production-design.md`
> **Goal:** Fix three compounding bugs causing detected highlight clips to become progressively longer and contain non-highlight content.

---

## 1. Problem Statement

After ~5–10 minutes of livestream processing, detected highlight clips exhibit two failure modes:

1. **Duration creep:** Clips grow from the expected 15–60s to 3–5 minutes or more.
2. **False positives:** Clips contain normal chatter or silence rather than genuine highlight moments.

### Root Causes (Identified)

| # | Location | Cause |
|---|---|---|
| **RC1** | `state_machine.py` | `MAX_EVENT_DURATION = 600s` — an ACTIVE event can run 10 minutes before forced close |
| **RC2** | `context_expander.py` | `look_back()` runs up to `MAX_LOOKBACK = 300s` with no early-exit when signal buffer is empty or scores are continuously low |
| **RC3** | `baseline_calibrator.py` + `aggregator.py` | After Phase 1 (300s), `close_thr = percentile(30)` of rolling scores; in an active stream this rises, making the state machine reluctant to close events |
| **RC4** | `highlight_processor.py` | No pre-filtering before LLM — low-score or oversized events enter the LLM queue |
| **RC5** | `llm_gate.py` | When rate-limited (`MIN_GAP_SEC = 30s`), `refine_boundary` returns `None` and the caller passes the unrefined boundary through to clip generation |

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM Gate | Keep, improve | LLM boundary refinement + content filter is sufficient; fix rate-limit passthrough |
| MAX_LOOKBACK | Keep at 300s | Value is fine; fix the logic that allows the full 300s to be consumed unnecessarily |
| Precision vs Recall | Recall-first | Prefer catching all highlights even with some false positives |
| Architecture | Fix in-place + add PreFilter | Minimal disruption; no new modules needed |
| Baseline Calibrator | No change | Fixing RC1/RC2/RC4 addresses symptoms; calibrator logic is separate concern |

---

## 3. Proposed Changes

### 3.1 StateMachine — Hard Active Duration Cap (RC1)

**File:** `src/engine/state_machine.py`

Reduce `MAX_EVENT_DURATION` from **600s → 120s**. At 120s, an ACTIVE event that hasn't closed naturally is almost certainly drift rather than a real highlight. The LLM gate downstream can still validate boundary quality.

```python
MAX_EVENT_DURATION = 120  # was 600
```

**Impact:** Events close sooner; `ContextExpander.expand()` receives a smaller `resolution_pts` window; `look_back()` has less drift opportunity.

---

### 3.2 ContextExpander — Early-Exit in look_back (RC2)

**File:** `src/engine/context_expander.py`

Add two new early-exit conditions to `look_back()`:

**Condition A — No data at all:**
If `has_history = False` (signal buffer is empty), stop looking back beyond `peak_pts - 30s` instead of scanning all 300s.

**Condition B — Sustained low-score zone without topic continuity:**
The existing low-score logic already exists but requires `topic_jaccard < TOPIC_THRESHOLD`. When `peak_keywords` is empty (no transcript yet), `topic_jaccard` always returns `1.0` (full similarity between two empty sets), disabling the topic stop. Add explicit guard: if both keyword sets are empty and `low_score_run >= LOW_SCORE_DURATION`, treat it as a stop condition.

New constant:
```python
NO_DATA_LOOKBACK_SEC = 30.0  # max lookback when history is unavailable
```

Logic change in `look_back()`:
```python
# Early exit: no signal history
if not has_history:
    return max(min_pts, peak_pts - self.NO_DATA_LOOKBACK_SEC)

# In the loop — fix empty keyword Jaccard bypass
if (
    low_score_run >= self.LOW_SCORE_DURATION
    and not peak_keywords  # both sets empty → jaccard = 1.0 falsely
    and last_high_pts is not None
):
    return last_high_pts
```

---

### 3.3 PreFilter in HighlightProcessor (RC4)

**File:** `src/engine/highlight_processor.py`

Add `_pre_filter(resolved: ResolvedEvent) -> Optional[ResolvedEvent]` called **before** `pending_queue.enqueue()` in `on_event_closed()`.

Rules (in order):

1. **Score too low** — reject immediately before spending an LLM call:
   ```python
   MIN_PEAK_SCORE = 0.35
   if resolved.peak_score < MIN_PEAK_SCORE:
       return None  # mark DB as REJECTED_PREFILTER
   ```

2. **Duration too long** — shrink boundary around peak, not reject:
   ```python
   MAX_PRE_LLM_DURATION = 90.0  # seconds
   SHRINK_LOOKBACK = 60.0
   duration = resolved.end_pts - resolved.start_pts
   if duration > MAX_PRE_LLM_DURATION:
       resolved = replace(
           resolved,
           start_pts=max(resolved.start_pts, resolved.peak_pts - SHRINK_LOOKBACK),
           end_pts=min(resolved.end_pts, resolved.peak_pts + 30.0),
       )
   ```

DB status for rejected events: `"REJECTED_PREFILTER"` (new status string, no schema change).

---

### 3.4 LLMGate — Fix Rate-Limited Passthrough + Richer Payload (RC5)

**File:** `src/engine/llm_gate.py`

#### 3.4.1 Distinguish rate-limit from hard failures

Change `refine_boundary` return contract: add a sentinel constant `RATE_LIMITED` so callers can distinguish "LLM unavailable temporarily" from "LLM call returned None due to error".

```python
RATE_LIMITED = "RATE_LIMITED"  # module-level sentinel string
```

`refine_boundary()` returns `Optional[LLMRefineResult]` as before, but `should_refine_boundary()` will signal the caller via a new method:

```python
def is_rate_limited(self) -> bool:
    """True if the next call would be blocked by MIN_GAP_SEC."""
    if self._last_call_time is None:
        return False
    return time.time() - self._last_call_time < self.MIN_GAP_SEC
```

#### 3.4.2 HighlightProcessor handles rate-limit

In `_maybe_refine_boundary()`:
```python
if self.llm_gate.is_rate_limited():
    # Re-enqueue with a short delay instead of passing through
    self.pending_queue.enqueue(resolved, current_pts=resolved.end_pts + 35.0)
    return None  # don't produce clip yet
```

> **Note:** This requires passing `current_pts` into `_maybe_refine_boundary`. The method signature change is minimal.

#### 3.4.3 Add duration_sec to LLM payload

In `refine_boundary()`, extend `payload`:
```python
payload["duration_sec"] = boundary.resolution_pts - boundary.trigger_pts
```

Update system prompt to instruct LLM:
```
If duration_sec > 90, be more critical — long clips are likely boundary errors.
Prefer shorter, punchy clips (15–60s) for TikTok.
```

---

## 4. Data Flow After Fix

```
StateMachine ACTIVE (max 120s)
    ↓ CLOSED
ContextExpander.look_back()
    ├── No history → stop at peak_pts - 30s
    └── Empty keywords + low score → stop early
    ↓ BoundaryResult
on_event_closed()
    ↓
[NEW] _pre_filter()
    ├── peak_score < 0.35 → REJECTED_PREFILTER (DB update)
    ├── duration > 90s → shrink around peak_pts
    └── pass
    ↓
pending_queue.enqueue()
    ↓
process_pending_queue()
    ↓
[FIX] _maybe_refine_boundary()
    ├── is_rate_limited() → re-enqueue at +35s
    └── not rate-limited → LLM call
        ├── is_valid=False → REJECTED_BY_AI
        └── is_valid=True, refined boundary → continue
    ↓
EventResolver → EventSplitter → ClipGenerator → FINAL
```

---

## 5. Constants Summary

| Constant | Location | Old Value | New Value | Reason |
|---|---|---|---|---|
| `MAX_EVENT_DURATION` | `state_machine.py` | `600` | `120` | Prevent 10-min events |
| `NO_DATA_LOOKBACK_SEC` | `context_expander.py` | N/A | `30.0` | Limit lookback when no history |
| `MIN_PEAK_SCORE` | `highlight_processor.py` | N/A | `0.35` | Pre-LLM score gate |
| `MAX_PRE_LLM_DURATION` | `highlight_processor.py` | N/A | `90.0` | Trim before LLM |
| `SHRINK_LOOKBACK` | `highlight_processor.py` | N/A | `60.0` | How far back to keep around peak |
| `MIN_GAP_SEC` | `llm_gate.py` | `30` | `30` (no change) | Rate limit unchanged |

---

## 6. Files Changed

| File | Change |
|---|---|
| `src/engine/state_machine.py` | `MAX_EVENT_DURATION` 600 → 120 |
| `src/engine/context_expander.py` | Add `NO_DATA_LOOKBACK_SEC`; early-exit in `look_back()` (2 conditions) |
| `src/engine/highlight_processor.py` | Add `_pre_filter()`; update `on_event_closed()` to call it; fix `_maybe_refine_boundary()` rate-limit handling |
| `src/engine/llm_gate.py` | Add `is_rate_limited()`; add `duration_sec` to payload; update system prompt |

---

## 7. Testing Strategy

### Automated

- `tests/engine/test_state_machine.py` — verify event closes at 120s
- `tests/engine/test_context_expander.py` — verify early-exit when `has_history=False`; verify early-exit when peak_keywords empty
- `tests/engine/test_highlight_processor.py` — verify `_pre_filter` rejects low-score events; verify oversized events are trimmed; verify rate-limited LLM causes re-enqueue
- `tests/engine/test_llm_gate.py` — verify `is_rate_limited()` returns True within 30s of last call

### Manual

- Start a TikTok stream, let run 10+ minutes
- Observe: no clip should exceed ~90s after LLM refine
- Observe: DRAFT highlights should close within 120s of opening

---

## 8. Out of Scope

- Fixing `BaselineCalibrator` threshold drift (deferred — not root cause for clip length)
- Changing `MIN_GAP_SEC` (rate limit value is correct, behavior fix is sufficient)
- Multi-platform testing (TikTok only for this fix)
