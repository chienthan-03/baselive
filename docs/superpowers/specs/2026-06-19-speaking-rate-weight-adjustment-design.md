# Design Spec: Speaking Rate Weight Adjustment and Enhanced Logging

This document specifies the changes required to increase the influence of the `speaking_rate` signal in highlight detection and improve visibility through enhanced logging.

## 1. Problem Statement
Currently, `speaking_rate` has a relatively low weight (0.13) compared to `energy` (0.22). In many livestream scenarios, a streamer's excitement is expressed through rapid speech rather than just increased volume. Increasing the weight of `speaking_rate` to match `energy` will make the highlight detection more sensitive to these high-energy verbal moments.

## 2. Proposed Changes

### 2.1. Signal Aggregator Weight Adjustment
The weights in `src/engine/aggregator.py` will be updated to balance the influence of audio signals. `speaking_rate` will be increased to 0.22, matching `energy`. To maintain a total weight of 1.0, other signals will be reduced proportionally, with a specific constraint to keep `chat_volume` at 0.13.

**New Weight Distribution:**
- `energy`: 0.22 (Unchanged)
- `speaking_rate`: 0.22 (+0.09)
- `chat_volume`: 0.13 (-0.01)
- `laughter`: 0.15 (-0.03)
- `pitch`: 0.08 (-0.01)
- `emoji_dominant`: 0.08 (-0.01)
- `overlap`: 0.04 (-0.01)
- `video_scene_change`: 0.04 (-0.01)
- `video_motion`: 0.04 (-0.01)

### 2.2. State Machine Logging Enhancement
The `StateMachine` log in `src/engine/state_machine.py` will be updated to include `speaking_rate` (as `speed`) for better real-time monitoring and debugging of the composite score.

**Log Format Change:**
From: `pts=%.1fs | score=%.3f (thr=%.2f/%.2f) | state=%s | energy=%.2f | laughter=%.2f | chat_vol=%.2f`
To: `pts=%.1fs | score=%.3f (thr=%.2f/%.2f) | state=%s | energy=%.2f | laughter=%.2f | chat_vol=%.2f | speed=%.2f`

## 3. Data Flow
1. `MasterPipeline.process_chunk` receives audio and transcript data.
2. `STTAnalyzer` calculates `speaking_rate`.
3. `SignalAggregator.compute_score` uses the new weights to calculate `composite_score`.
4. `StateMachine.process` logs the snapshot signals including the new `speed` field.

## 4. Testing Plan
- **Unit Test:** Verify `SignalAggregator` weights sum to 1.0.
- **Integration Test:** Run a sample stream chunk and verify the log output contains the `speed` field.
- **Validation:** Compare highlight scores for fast-talking segments before and after the change.
