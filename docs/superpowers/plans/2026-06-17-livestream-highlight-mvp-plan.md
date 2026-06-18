# MVP Implementation Plan — BaseLive Highlight Extraction

> **Status:** ✅ Phase 1 hoàn tất (Phases 1.1 → 1.6)
> **Tests:** 30/30 passing

---

## Phase 1.1: Core Data Structures & DSP Pipeline ✅ DONE

**Goal:** Xây dựng core data structures (4 Circular Buffers) và Audio DSP cơ bản.

### Task 1: Comprehensive Signal Snapshot & Events ✅

**Files:**
- `src/core/models.py`
- `tests/core/test_models.py`

- [x] **Step 1: Write the failing test**
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Write minimal implementation**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Commit** — `feat: define core data models`

### Task 2: Core Circular Buffers Implementation ✅

**Files:**
- `src/buffer/circular_buffer.py`
- `tests/buffer/test_circular_buffer.py`

- [x] **Step 1: Write the failing test for all buffers**
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Write minimal implementation**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Commit** — `feat: implement all 4 circular buffers`

### Task 3: Basic Audio DSP Analyzer ✅

**Files:**
- `src/pipeline/audio_dsp.py`
- `tests/pipeline/test_audio_dsp.py`

- [x] **Step 1: Write the failing tests**
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Write minimal implementation**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Commit** — `feat: implement basic DSP analyzer with energy and silence tracking`

---

## Phase 1.2: Signal Aggregator & STT Pipeline ✅ DONE

**Goal:** Xây dựng Signal Aggregator tổng hợp signals và STT Worker stub.

### Task 1: Signal Aggregator Engine ✅

**Files:**
- `src/engine/aggregator.py`
- `tests/engine/test_aggregator.py`

- [x] Viết test
- [x] Implement `SignalAggregator.compute_score()` — tính composite score từ audio & chat signals
- [x] Tests pass
- [x] Commit — `feat: implement signal aggregator`

### Task 2: STT Worker Stub ✅

**Files:**
- `src/pipeline/stt_worker.py`
- `tests/pipeline/test_stt_worker.py`

- [x] Viết test
- [x] Implement `STTWorker` (faster-whisper stub, đọc audio chunks)
- [x] Tests pass
- [x] Commit — `feat: implement STT worker stub`

---

## Phase 1.3: Chat Analyzer & Master Pipeline Controller ✅ DONE

**Goal:** Xây dựng Chat Analyzer (rule-based) và Master Pipeline orchestrator.

### Task 1: TikTok Chat Analyzer ✅

**Files:**
- `src/pipeline/chat_analyzer.py`
- `tests/pipeline/test_chat_analyzer.py`

- [x] Viết test — volume spike, emoji detection, keyword matching
- [x] Implement `ChatAnalyzer.analyze_batch()` — volume spike, keyword triggers
- [x] Tests pass
- [x] Commit — `feat: implement chat analyzer`

### Task 2: Master Pipeline Controller ✅

**Files:**
- `src/engine/pipeline.py`
- `tests/engine/test_pipeline.py`

- [x] Viết test — end-to-end pipeline integration
- [x] Implement `MasterPipeline.process_chunk()` — kết nối AudioAnalyzer, ChatAnalyzer, SignalAggregator, StateMachine
- [x] Implement `StateMachine` — IDLE → OPENING → ACTIVE → CLOSED transitions
- [x] Tests pass
- [x] Commit — `feat: implement master pipeline controller`

---

## Phase 1.4: Clip Generator ✅ DONE

**Goal:** Xây dựng ClipGenerator dùng FFmpeg để xuất highlight clips.

### Task 1: ClipGenerator Core ✅

**Files:**
- `src/engine/clip_generator.py`
- `tests/engine/test_clip_generator.py`

- [x] Viết test — FFmpeg command generation, output path format
- [x] Implement `ClipGenerator.generate()` — tính start/duration với pre-roll & post-roll, gọi FFmpeg
- [x] Tests pass
- [x] Commit — `feat: implement clip generator`

### Task 2: ClipGenerator Integration with MasterPipeline ✅

- [x] Tích hợp `ClipGenerator` vào `MasterPipeline` — emit clip khi event CLOSED
- [x] Tests pass
- [x] Commit — `feat: integrate clip generator with master pipeline`

---

## Phase 1.5: Data Ingestion ✅ DONE

**Goal:** Xây dựng lớp ingestion đầu vào từ TikTok Live stream.

### Task 1: StreamRecorder (yt-dlp + FFmpeg Audio Feeder) ✅

**Files:**
- `src/ingestion/stream_recorder.py`
- `tests/ingestion/test_stream_recorder.py`

- [x] Viết test
- [x] Implement — spawn `yt-dlp | ffmpeg`, đọc PCM float32, push vào `AudioRingBuffer`
- [x] Tests pass
- [x] Commit

### Task 2: ChatCollector (TikTok-Live-Connector Bridge) ✅

**Files:**
- `src/ingestion/chat_collector.py`
- `tests/ingestion/test_chat_collector.py`

- [x] Viết test
- [x] Implement — spawn Node.js bridge, parse newline-delimited JSON, push vào `ChatBuffer`
- [x] Tests pass
- [x] Commit

### Task 3: StreamWorker (Per-Stream Orchestrator) ✅

**Files:**
- `src/ingestion/stream_worker.py`
- `tests/ingestion/test_stream_worker.py`

- [x] Viết test
- [x] Implement — quản lý vòng đời StreamRecorder + ChatCollector, reconnect loop với exponential backoff, poll buffer mỗi 5s, gọi `pipeline.process_chunk()`
- [x] Tests pass
- [x] Commit

### Task 4: Node.js TikTok Bridge Script ✅

**Files:**
- `tools/tiktok_bridge/index.js`
- `tools/tiktok_bridge/package.json`
- `tools/tiktok_bridge/README.md`

- [x] Implement Node.js script dùng `tiktok-live-connector` — emit JSON events qua stdout
- [x] Commit

### Task 5: Integration Smoke Test ✅

**Files:**
- `tests/integration/test_smoke.py`

- [x] Viết test end-to-end — inject loud audio + hype chat vào pipeline
- [x] Assert StateMachine chuyển sang `OPENING` hoặc `ACTIVE`
- [x] Test pass
- [x] Commit — `feat: complete Phase 1.5 Data Ingestion`

---

## Phase 1.6: Web Dashboard ✅ DONE

**Goal:** Editor UI để review, approve/reject, và tinh chỉnh highlight clips.

### Task 1: SQLite Database Setup & Pipeline Integration ✅

**Files:**
- `src/db/database.py`
- `tests/db/test_database.py`

- [x] Viết test — CRUD operations cho `highlights` table
- [x] Implement `Database` wrapper — `insert_highlight()`, `get_highlights()`, `update_status()`, `update_boundaries()`
- [x] Tích hợp vào `MasterPipeline` — auto-insert khi event CLOSED
- [x] Tests pass (4/4)
- [x] Commit

### Task 2: FastAPI Backend Setup (Endpoints) ✅

**Files:**
- `src/api/main.py`
- `tests/api/test_routes.py`

- [x] Viết test — 4 endpoints với TestClient
- [x] Implement endpoints:
  - `GET /` — serve `index.html`
  - `GET /api/highlights` — danh sách highlights từ SQLite
  - `POST /api/highlights/{id}/approve` — duyệt
  - `POST /api/highlights/{id}/reject` — từ chối
  - `POST /api/highlights/{id}/adjust` — cập nhật ranh giới start/end
- [x] Mount `/static` và `/clips` StaticFiles
- [x] Tests pass (4/4)
- [x] Commit

### Task 3: Premium UI Frontend (HTML/CSS/JS) ✅

**Files:**
- `src/api/static/index.html`
- `src/api/static/css/styles.css`
- `src/api/static/js/app.js`

- [x] `index.html` — 2-panel layout (queue sidebar + preview panel), semantic HTML, ARIA
- [x] `styles.css` — Premium Dark Mode + Glassmorphism, animated background orbs, score ring SVG, range sliders, micro-animations, responsive
- [x] `app.js` — fetch/render highlights, filter tabs, video player, boundary sliders, approve/reject/adjust actions, polling 8s, toast notifications
- [x] Commit

### Task 4: UI / API Integration Test ✅

- [x] Chạy toàn bộ test suite: **30/30 pass**
- [x] Commit — `feat: Phase 1.6 Web Dashboard (SQLite, FastAPI API, Premium dark-mode UI)`

---

## Tổng kết MVP Phase 1

| Phase | Nội dung | Tests | Status |
|-------|----------|-------|--------|
| 1.1 | Core Models + Circular Buffers + Audio DSP | 6 tests | ✅ |
| 1.2 | Signal Aggregator + STT Worker | 2 tests | ✅ |
| 1.3 | Chat Analyzer + Master Pipeline | 3 tests | ✅ |
| 1.4 | Clip Generator | 4 tests | ✅ |
| 1.5 | Data Ingestion (StreamRecorder, ChatCollector, StreamWorker, Bridge) | 9 tests | ✅ |
| 1.6 | Web Dashboard (SQLite, FastAPI, Premium UI) | 8 tests | ✅ |
| **TỔNG** | | **30/30** | **✅ DONE** |

### Khởi chạy Dashboard

```powershell
cd c:\Publish\base-live
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --reload --port 8000
# → http://localhost:8000
```
