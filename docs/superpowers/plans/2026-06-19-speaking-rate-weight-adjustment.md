# Speaking Rate Weight Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase the weight of `speaking_rate` to 0.22 in highlight detection and enhance logging to include speed.

**Architecture:** Update static weights in `SignalAggregator` and modify the logging format in `StateMachine`.

**Tech Stack:** Python, Pytest

---

### Task 1: Update Signal Weights

**Files:**
- Modify: `src/engine/aggregator.py:6-16`
- Test: `tests/engine/test_aggregator.py`

- [x] **Step 1: Write a test to verify weights sum to 1.0**

```python
from src.engine.aggregator import WEIGHTS

def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == 1.0
```

- [x] **Step 2: Run test to verify it passes (with current weights)**

Run: `pytest tests/engine/test_aggregator.py -v`
Expected: PASS

- [x] **Step 3: Update WEIGHTS in aggregator.py**

```python
WEIGHTS: Dict[str, float] = {
    "energy": 0.22,
    "laughter": 0.15,
    "chat_volume": 0.13,
    "speaking_rate": 0.22,
    "pitch": 0.08,
    "emoji_dominant": 0.08,
    "overlap": 0.04,
    "video_scene_change": 0.04,
    "video_motion": 0.04,
}
```

- [x] **Step 4: Run test to verify it still passes**

Run: `pytest tests/engine/test_aggregator.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/engine/aggregator.py
git commit -m "feat: update signal weights to prioritize speaking_rate"
```

### Task 2: Enhance State Machine Logging

**Files:**
- Modify: `src/engine/state_machine.py:37-47`
- Test: `tests/engine/test_state_machine.py`

- [x] **Step 1: Update the log format and parameters**

```python
        logger.info(
            "pts=%.1fs | score=%.3f (thr=%.2f/%.2f) | state=%s | energy=%.2f | laughter=%.2f | chat_vol=%.2f | speed=%.2f",
            pts,
            score,
            open_thr,
            confirm_thr,
            ev.state,
            snapshot.audio_energy,
            snapshot.laughter_prob,
            snapshot.chat_volume_spike,
            snapshot.speaking_rate,
        )
```

- [x] **Step 2: Run existing tests to ensure no regression**

Run: `pytest tests/engine/test_state_machine.py -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add src/engine/state_machine.py
git commit -m "feat: add speaking_rate to state machine logs"
```
