# Phase 1.7: MVP Signal Layer Completion — Implementation Plan

> **Status:** ✅ DONE — 47/47 tests passing
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Hoàn thiện signal layer theo spec PHẦN 2 — nối STT, mở rộng DSP/chat, scoring đầy đủ, rolling video file, và harden state machine.

**Architecture:** Incremental TDD qua 6 sub-phases (1.7a→1.7f). Mỗi sub-phase có test riêng, commit riêng. Graceful degrade khi signal source fail.

**Tech Stack:** Python 3.11+, numpy, faster-whisper (small/int8/CPU), pytest, FFmpeg, yt-dlp.

**Design spec:** `docs/superpowers/specs/2026-06-18-mvp-signal-layer-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/ingestion/stream_recorder.py` | Modify | Dual FFmpeg output: audio PCM + rolling video |
| `src/pipeline/stt_worker.py` | Modify | Structured `TranscriptResult` output |
| `src/pipeline/stt_analyzer.py` | Create | Transcript → speaking_rate, keywords, sentiment |
| `src/pipeline/audio_dsp.py` | Modify | Add pitch, laughter, overlap signals |
| `src/pipeline/chat_analyzer.py` | Modify | Emoji, gift, spam, field fix |
| `src/core/models.py` | Modify | Extended `SignalSnapshot`, new transcript dataclasses |
| `src/engine/aggregator.py` | Modify | excitement_score formula + bonuses |
| `src/engine/state_machine.py` | Create | Extracted state machine with hardening |
| `src/engine/pipeline.py` | Modify | Wire all analyzers, new process_chunk signature |
| `src/ingestion/stream_worker.py` | Modify | STT + TranscriptBuffer + video_path wiring |
| `src/engine/clip_generator.py` | Modify | PTS offset support for rotated video files |
| `tests/ingestion/test_stream_recorder.py` | Modify | Video output tests |
| `tests/pipeline/test_stt_worker.py` | Modify | Structured output tests |
| `tests/pipeline/test_stt_analyzer.py` | Create | STTAnalyzer tests |
| `tests/pipeline/test_audio_dsp.py` | Modify | Extended DSP tests |
| `tests/pipeline/test_chat_analyzer.py` | Modify | Full chat analyzer tests |
| `tests/core/test_models.py` | Modify | Extended snapshot tests |
| `tests/engine/test_aggregator.py` | Modify | New scoring formula tests |
| `tests/engine/test_state_machine.py` | Create | State machine tests |
| `tests/engine/test_pipeline.py` | Modify | Full wiring tests |
| `tests/ingestion/test_stream_worker.py` | Modify | STT wiring tests |
| `tests/integration/test_smoke.py` | Modify | Extended smoke test |

---

## Phase 1.7a: StreamRecorder Video Output

### Task 1: Rolling video file recording

**Files:**
- Modify: `src/ingestion/stream_recorder.py`
- Modify: `tests/ingestion/test_stream_recorder.py`

- [x] **Step 1: Write the failing test**

```python
def test_stream_recorder_exposes_video_path(tmp_path):
    audio_buffer = AudioRingBuffer(capacity_sec=60, sample_rate=16000)
    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=audio_buffer,
        stream_id="test_stream",
        video_output_dir=str(tmp_path),
    )
    assert recorder.video_path.endswith("live.mp4")
    assert str(tmp_path) in recorder.video_path
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_stream_recorder.py::test_stream_recorder_exposes_video_path -v`
Expected: FAIL (`stream_id` or `video_path` not defined)

- [x] **Step 3: Write minimal implementation**

Add to `StreamRecorder.__init__`:
- `stream_id: str = "default"`
- `video_output_dir: str = "output/streams"`
- Create dir, set `self.video_path = os.path.join(video_output_dir, stream_id, "live.mp4")`
- `self.pts_offset: float = 0.0`

Update `_FFMPEG_CMD` to dual output using `-map 0:a` for PCM stdout and `-map 0:v` for video file with `-c copy -movflags +frag_keyframe+empty_moov`.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/test_stream_recorder.py -v`
Expected: PASS (all recorder tests)

- [x] **Step 5: Commit**

```bash
git add src/ingestion/stream_recorder.py tests/ingestion/test_stream_recorder.py
git commit -m "feat(1.7a): add rolling video file output to StreamRecorder"
```

### Task 2: Video file rotation

**Files:**
- Modify: `src/ingestion/stream_recorder.py`
- Modify: `tests/ingestion/test_stream_recorder.py`

- [x] **Step 1: Write the failing test**

```python
def test_stream_recorder_rotates_video_file(tmp_path):
    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=AudioRingBuffer(capacity_sec=60, sample_rate=16000),
        stream_id="rot_test",
        video_output_dir=str(tmp_path),
        max_video_duration_s=1.0,  # short for test
    )
    recorder._rotate_video_file()
    assert "live_001.mp4" in recorder.video_path or recorder.pts_offset > 0
```

- [x] **Step 2: Run test — expect FAIL**

- [x] **Step 3: Implement `_rotate_video_file()`** — increment file counter, update `pts_offset`, restart video FFmpeg output branch.

- [x] **Step 4: Run tests — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7a): add video file rotation with PTS offset tracking"
```

---

## Phase 1.7b: STT Integration

### Task 3: TranscriptResult dataclasses

**Files:**
- Modify: `src/core/models.py`
- Modify: `tests/core/test_models.py`

- [x] **Step 1: Write the failing test**

```python
from src.core.models import TranscriptResult, TranscriptSegment

def test_transcript_result_structure():
    seg = TranscriptSegment(start=0.0, end=1.2, text="xin chào", confidence=0.92)
    result = TranscriptResult(
        text="xin chào",
        segments=[seg],
        language="vi",
        chunk_start_pts=10.0,
    )
    assert result.segments[0].text == "xin chào"
```

- [x] **Step 2: Run test — expect FAIL**

- [x] **Step 3: Add dataclasses to `src/core/models.py`**

- [x] **Step 4: Run test — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7b): add TranscriptResult and TranscriptSegment models"
```

### Task 4: STTWorker structured output

**Files:**
- Modify: `src/pipeline/stt_worker.py`
- Modify: `tests/pipeline/test_stt_worker.py`

- [x] **Step 1: Write the failing test**

```python
def test_stt_returns_transcript_result():
    worker = STTWorker(model_size="tiny")
    worker.model = MagicMock()
    mock_seg = MagicMock()
    mock_seg.start = 0.0
    mock_seg.end = 1.0
    mock_seg.text = "Hello highlight"
    mock_seg.avg_logprob = -0.3
    worker.model.transcribe.return_value = ([mock_seg], None)

    result = worker.transcribe_chunk(np.zeros(16000), chunk_start_pts=5.0)
    assert result.text == "Hello highlight"
    assert result.chunk_start_pts == 5.0
    assert len(result.segments) == 1
```

- [x] **Step 2: Run test — expect FAIL**

- [x] **Step 3: Change `transcribe_chunk()` to return `TranscriptResult`**, map segment confidence from `avg_logprob`. Add `enabled` property.

- [x] **Step 4: Run tests — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7b): STTWorker returns structured TranscriptResult"
```

### Task 5: STTAnalyzer

**Files:**
- Create: `src/pipeline/stt_analyzer.py`
- Create: `tests/pipeline/test_stt_analyzer.py`

- [x] **Step 1: Write the failing test**

```python
from src.pipeline.stt_analyzer import STTAnalyzer
from src.core.models import TranscriptResult, TranscriptSegment

def test_stt_analyzer_speaking_rate_and_keywords():
    analyzer = STTAnalyzer()
    result = TranscriptResult(
        text="ôi trời ơi thật không",
        segments=[TranscriptSegment(0, 2, "ôi trời ơi thật không", 0.9)],
        language="vi",
        chunk_start_pts=0.0,
    )
    out = analyzer.analyze(result, duration_sec=2.0)
    assert out["speaking_rate"] > 0
    assert len(out["keyword_triggered"]) > 0
```

- [x] **Step 2: Run test — expect FAIL**

- [x] **Step 3: Implement `STTAnalyzer.analyze()`** with speaking_rate heuristic, SHOCK keyword list (`ôi`, `trời ơi`, `omg`), sentiment_shift from positive/negative word lists.

- [x] **Step 4: Run test — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7b): add STTAnalyzer for speaking rate and keyword signals"
```

---

## Phase 1.7c: Audio DSP Extensions

### Task 6: Pitch, laughter, overlap signals

**Files:**
- Modify: `src/pipeline/audio_dsp.py`
- Modify: `tests/pipeline/test_audio_dsp.py`

- [x] **Step 1: Write the failing tests**

```python
def test_audio_dsp_returns_extended_signals():
    analyzer = AudioAnalyzer(sample_rate=16000)
    audio = np.random.normal(0, 0.3, 16000 * 5)
    res = analyzer.analyze_chunk(audio)
    assert "pitch_deviation" in res
    assert "laughter_prob" in res
    assert "speaker_overlap" in res
    assert 0.0 <= res["laughter_prob"] <= 1.0

def test_laughter_detected_on_hf_burst():
    analyzer = AudioAnalyzer(sample_rate=16000)
    # Synthetic: alternating high-freq bursts
    t = np.linspace(0, 5, 16000 * 5)
    burst = np.sin(2 * np.pi * 800 * t) * (np.sin(2 * np.pi * 4 * t) > 0)
    res = analyzer.analyze_chunk(burst.astype(np.float32))
    assert res["laughter_prob"] > 0.3
```

- [x] **Step 2: Run tests — expect FAIL**

- [x] **Step 3: Implement in `AudioAnalyzer`:**
  - `_estimate_pitch()` — autocorrelation per 100ms frame
  - `_detect_laughter()` — HF energy ratio + burst periodicity
  - `_estimate_overlap()` — energy variance across frames
  - `pitch_deviation` = normalized deviation from `self.baseline_pitch`

- [x] **Step 4: Run tests — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7c): extend AudioAnalyzer with pitch, laughter, overlap"
```

---

## Phase 1.7d: Chat Analyzer Full

### Task 7: Emoji, gift, spam, field fix

**Files:**
- Modify: `src/pipeline/chat_analyzer.py`
- Modify: `tests/pipeline/test_chat_analyzer.py`

- [x] **Step 1: Write the failing tests**

```python
def test_chat_analyzer_emoji_categories():
    analyzer = ChatAnalyzer()
    messages = [
        {"content": "😂😂😂", "event_type": "COMMENT"},
        {"content": "haha", "event_type": "COMMENT"},
    ]
    result = analyzer.analyze_batch(messages)
    assert result["chat_emoji_scores"]["funny"] > 0

def test_chat_analyzer_gift_detection():
    analyzer = ChatAnalyzer()
    messages = [{"event_type": "GIFT", "content": "sent rose", "gift_value": 500}]
    result = analyzer.analyze_batch(messages)
    assert result["gift_event"] is not None
    assert result["gift_event"]["value"] == 500

def test_chat_analyzer_spam_filter():
    analyzer = ChatAnalyzer()
    messages = [{"content": "spam", "username": "bot"}] * 5
    result = analyzer.analyze_batch(messages)
    assert result["raw_volume"] == 0  # all filtered
```

- [x] **Step 2: Run tests — expect FAIL**

- [x] **Step 3: Implement:**
  - `_normalize_text(m)` → `content` or `msg`
  - `_filter_spam(messages)` before analysis
  - `_score_emojis(text)` → dict with funny/shock/love/sad
  - `_detect_gift(messages)` → gift_event dict or None
  - `_detect_keyword_cluster(messages)` → cluster name or None

- [x] **Step 4: Run tests — expect PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7d): full ChatAnalyzer with emoji, gift, spam filter"
```

---

## Phase 1.7e: SignalSnapshot + Aggregator Rewrite

### Task 8: Extended SignalSnapshot

**Files:**
- Modify: `src/core/models.py`
- Modify: `tests/core/test_models.py`

- [x] **Step 1: Write the failing test**

```python
def test_signal_snapshot_extended_fields():
    snapshot = SignalSnapshot(
        pts=1.0,
        pitch_deviation=0.5,
        laughter_prob=0.8,
        chat_emoji_scores={"funny": 0.7},
    )
    assert snapshot.laughter_prob == 0.8
    assert snapshot.chat_emoji_scores["funny"] == 0.7
```

- [x] **Step 2–4: Add fields per design spec §4.5, verify PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7e): extend SignalSnapshot with full spec fields"
```

### Task 9: SignalAggregator excitement formula

**Files:**
- Modify: `src/engine/aggregator.py`
- Modify: `tests/engine/test_aggregator.py`

- [x] **Step 1: Write the failing test**

```python
def test_aggregator_excitement_formula():
    agg = SignalAggregator()
    snapshot = SignalSnapshot(
        pts=10.0,
        audio_energy_spike=True,
        laughter_prob=0.8,
        chat_volume_spike=1.0,
        speaking_rate=0.7,
        pitch_deviation=0.5,
        speaker_overlap=0.2,
        chat_emoji_scores={"funny": 0.9},
        silence_before=3.0,
        keyword_triggered=["ôi"],
    )
    score = agg.compute_score(snapshot)
    assert score > 0.6  # bonuses applied
```

- [x] **Step 2: Run test — expect FAIL** (old 3-weight formula gives different result)

- [x] **Step 3: Rewrite `compute_score()`:**
  - Normalize each signal 0–1 via rolling deque (60 snapshots)
  - Apply §2.1.6 weights
  - Apply bonus multipliers
  - `redistribute_weights()` when source disabled

- [x] **Step 4: Update existing `test_aggregator_weights` or replace with new formula test — PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7e): rewrite SignalAggregator with excitement formula"
```

---

## Phase 1.7f: StateMachine + Full Integration

### Task 10: Extract StateMachine

**Files:**
- Create: `src/engine/state_machine.py`
- Create: `tests/engine/test_state_machine.py`
- Modify: `src/engine/pipeline.py`

- [x] **Step 1: Write the failing tests**

```python
from src.engine.state_machine import StateMachine
from src.core.models import SignalSnapshot

def test_state_machine_forced_close_at_max_duration():
    sm = StateMachine()
    sm.current_event.state = "ACTIVE"
    sm.current_event.start_pts = 0.0
    snapshot = SignalSnapshot(pts=601.0, composite_score=0.9)
    sm.process(snapshot)
    assert sm.current_event.state == "CLOSED"

def test_state_machine_appends_signals():
    sm = StateMachine()
    sm.process(SignalSnapshot(pts=1.0, composite_score=0.9))
    assert len(sm.current_event.signals) >= 1
```

- [x] **Step 2: Run tests — expect FAIL**

- [x] **Step 3: Move `StateMachine` from `pipeline.py` to `state_machine.py`**, add `MAX_EVENT_DURATION=600`, `signals` list, chat cooldown check (accept `chat_volume_ratio` param in `process()`).

- [x] **Step 4: Update `pipeline.py` import — all tests PASS**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7f): extract StateMachine with forced close and signal history"
```

### Task 11: MasterPipeline full wiring

**Files:**
- Modify: `src/engine/pipeline.py`
- Modify: `tests/engine/test_pipeline.py`

- [x] **Step 1: Write the failing test**

```python
def test_pipeline_populates_full_snapshot():
    pipeline = MasterPipeline()
    audio = np.random.normal(0, 0.8, 16000 * 5)
    chat = [{"content": "😂😂", "event_type": "COMMENT"}] * 10
    transcript = [{"item": TranscriptResult(text="ôi trời", segments=[], language="vi", chunk_start_pts=0), "pts": 0}]
    pipeline.process_chunk(pts=10.0, audio_data=audio, chat_messages=chat, transcript=transcript)
    assert pipeline.state_machine.current_event.state in ["OPENING", "ACTIVE"]
```

- [x] **Step 2–4: Update `process_chunk()`** to accept `transcript` and `clip_source`, wire STTAnalyzer, populate all SignalSnapshot fields, update clip_generator source dynamically.

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7f): wire full signal layer in MasterPipeline"
```

### Task 12: StreamWorker STT + video wiring

**Files:**
- Modify: `src/ingestion/stream_worker.py`
- Modify: `tests/ingestion/test_stream_worker.py`

- [x] **Step 1: Write the failing test**

```python
@patch("src.ingestion.stream_worker.STTWorker")
def test_stream_worker_passes_transcript_to_pipeline(MockSTT):
    mock_stt = MockSTT.return_value
    mock_stt.enabled = True
    mock_stt.transcribe_chunk.return_value = TranscriptResult(text="test", segments=[], language="vi", chunk_start_pts=0)
    # ... setup worker with max_iterations=1, inject audio ...
    # assert pipeline.process_chunk called with transcript= keyword arg
```

- [x] **Step 2–4: Add TranscriptBuffer, STTWorker init with try/except, transcribe each chunk, pass transcript + video_path to pipeline.**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7f): wire STT and video path in StreamWorker"
```

### Task 13: ClipGenerator PTS offset

**Files:**
- Modify: `src/engine/clip_generator.py`
- Modify: `tests/engine/test_clip_generator.py`

- [x] **Step 1: Write the failing test**

```python
def test_clip_generator_applies_pts_offset():
    gen = ClipGenerator(source_file="live.mp4", output_dir="out", pts_offset=100.0)
    event = EventCandidate(start_pts=110.0, end_pts=120.0, peak_score=0.8)
    cmd = gen.build_ffmpeg_cmd(event)  # extract cmd builder for testability
    assert "-ss" in cmd
    ss_index = cmd.index("-ss")
    assert float(cmd[ss_index + 1]) == pytest.approx(10.0)  # 110 - 100 pre_roll handled separately
```

- [x] **Step 2–4: Add `pts_offset` param, refactor `build_ffmpeg_cmd()` for testing.**

- [x] **Step 5: Commit**

```bash
git commit -m "feat(1.7f): ClipGenerator supports PTS offset for rotated video"
```

### Task 14: Extended integration smoke test

**Files:**
- Modify: `tests/integration/test_smoke.py`

- [x] **Step 1: Extend smoke test** — inject loud audio + gift chat (`event_type=GIFT, gift_value=500`) + transcript with shock keyword.

- [x] **Step 2: Run full suite**

Run: `pytest -v`
Expected: **~45–50 tests PASS**

- [x] **Step 3: Commit**

```bash
git commit -m "test(1.7f): extend integration smoke test for full signal layer"
```

### Task 15: Update plan status

**Files:**
- Modify: `docs/superpowers/plans/2026-06-17-livestream-highlight-mvp-plan.md`

- [x] Append Phase 1.7 summary table with test count and link to this plan.

- [x] **Commit**

```bash
git add docs/
git commit -m "docs: add Phase 1.7 signal layer plan and update MVP status"
```

---

## Tổng kết Phase 1.7 ✅ DONE

| Sub-phase | Nội dung | Tests |
|---|---|---|
| 1.7a | StreamRecorder video | ✅ |
| 1.7b | STT + STTAnalyzer | ✅ |
| 1.7c | Audio DSP extensions | ✅ |
| 1.7d | Chat Analyzer full | ✅ |
| 1.7e | Snapshot + Aggregator | ✅ |
| 1.7f | StateMachine + integration | ✅ |
| **TỔNG** | | **47/47** |

### Không nằm trong plan này

- Live TikTok E2E (manual QA)
- Dynamic context expansion
- SVM laughter / GPU STT
- VideoBuffer TS segments
