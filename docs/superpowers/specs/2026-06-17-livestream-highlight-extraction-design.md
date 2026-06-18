# AI Livestream Highlight Extraction System — Technical Design Document

> **Version:** 1.0 — Draft  
> **Date:** 2026-06-17  
> **Architecture Approach:** LLM-Minimal (Rule-based chính, LLM chỉ refine)  
> **MVP Platform:** TikTok Live  
> **Ngôn ngữ chính:** Tiếng Việt  
> **Quy mô MVP:** 1–3 livestream đồng thời  
> **Budget:** < $100/tháng  
> **Deployment:** Internal tool, team nhỏ  

---

## Mục lục

1. [Kiến trúc tổng thể](#phần-0--kiến-trúc-tổng-thể)
2. [Livestream Ingestion](#phần-1--livestream-ingestion)
3. [Realtime Processing Pipeline](#phần-2--realtime-processing-pipeline)
4. [Highlight Extraction Engine](#phần-3--highlight-extraction-engine)
5. [Hidden Complexity Solutions](#phần-4--hidden-complexity-solutions)
6. [AI vs Non-AI Architecture](#phần-5--ai-vs-non-ai-architecture)
7. [Event Candidate State Machine](#phần-6--event-candidate-state-machine)
8. [Clip Generation](#phần-7--clip-generation)
9. [Realtime Export](#phần-8--realtime-export)
10. [AI Models Selection](#phần-9--ai-models-selection)
11. [Scalability Design](#phần-10--scalability-design)
12. [Cost Optimization](#phần-11--cost-optimization)
13. [MVP Roadmap](#phần-12--mvp-roadmap)
14. [Risk Register](#phần-13--risk-register)

---

## PHẦN 0 — Kiến trúc tổng thể

### Sơ đồ kiến trúc High-Level

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LIVESTREAM SOURCES                              │
│   ┌──────────┐  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐  │
│   │ TikTok   │  │ YouTube Live │  │ Facebook Live │  │ Twitch/Other│  │
│   │ Live     │  │ (Phase 2)    │  │ (Phase 2)     │  │ (Phase 3)   │  │
│   └────┬─────┘  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘  │
└────────┼───────────────┼──────────────────┼──────────────────┼─────────┘
         │               │                  │                  │
         ▼               ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    INGESTION LAYER (Per-Stream Worker)                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐    │
│  │ Stream Recorder│  │ Chat Collector │  │ Platform Adapter       │    │
│  │ (HLS/FLV pull) │  │ (WebSocket)    │  │ (abstract per-platform)│    │
│  └───────┬────────┘  └───────┬────────┘  └────────────────────────┘    │
│          │                   │                                         │
│          ▼                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              CIRCULAR BUFFER (Per-Stream)                        │   │
│  │  ┌─────────┐ ┌─────────┐ ┌────────────┐ ┌──────────────────┐   │   │
│  │  │ Video   │ │ Audio   │ │ Transcript │ │ Chat Messages    │   │   │
│  │  │ Buffer  │ │ Buffer  │ │ Buffer     │ │ Buffer           │   │   │
│  │  │ (10min) │ │ (10min) │ │ (15min)    │ │ (15min)          │   │   │
│  │  └────┬────┘ └────┬────┘ └─────┬──────┘ └───────┬──────────┘   │   │
│  └───────┼───────────┼────────────┼────────────────┼──────────────┘   │
└──────────┼───────────┼────────────┼────────────────┼──────────────────┘
           │           │            │                │
           ▼           ▼            ▼                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 REALTIME PROCESSING PIPELINE                           │
│                                                                        │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │ STT Engine   │ │ Audio DSP    │ │ Chat      │ │ Video Analysis   │ │
│  │ (Whisper/    │ │ (energy,     │ │ Analyzer  │ │ (scene change,   │ │
│  │  PhoWhisper) │ │ pitch,       │ │ (rule-    │ │  motion detect)  │ │
│  │ [LOCAL/CPU]  │ │ silence)     │ │ based)    │ │ [LOCAL/CPU]      │ │
│  │              │ │ [LOCAL/CPU]  │ │ [CPU]     │ │ (Phase 2)        │ │
│  └──────┬───────┘ └──────┬───────┘ └─────┬─────┘ └────────┬─────────┘ │
│         │                │               │                 │           │
│         ▼                ▼               ▼                 ▼           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              SIGNAL AGGREGATOR & TIMESTAMP ALIGNMENT             │   │
│  │         (Master Clock = Video PTS, drift correction)             │   │
│  └─────────────────────────┬────────────────────────────────────────┘   │
└────────────────────────────┼────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              HIGHLIGHT EXTRACTION ENGINE (Core)                        │
│                                                                        │
│  ┌────────────────┐  ┌────────────────────┐  ┌──────────────────────┐  │
│  │ Event Detector │  │ Event State Machine│  │ Dynamic Context      │  │
│  │ (signal-based  │  │ (OPENING → ACTIVE  │  │ Expansion            │  │
│  │  threshold)    │  │  → CLOSED)         │  │ (look-back/forward)  │  │
│  └───────┬────────┘  └─────────┬──────────┘  └──────────┬───────────┘  │
│          │                     │                        │              │
│          ▼                     ▼                        ▼              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              HIGHLIGHT RANKER & BOUNDARY DETECTOR                │   │
│  │  Score = w1*Drama + w2*Shock + w3*Emotion + w4*Retention + ...   │   │
│  └─────────────────────────┬────────────────────────────────────────┘   │
│                            │                                           │
│              ┌─────────────┼────────────────┐                          │
│              ▼             ▼                ▼                           │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐            │
│  │ Overlap      │ │ Long Event   │ │ LLM Gate            │            │
│  │ Resolution   │ │ Splitter     │ │ (chỉ gọi khi cần   │            │
│  │              │ │              │ │  refine boundary)    │            │
│  └──────┬───────┘ └──────┬───────┘ └──────────┬──────────┘            │
└─────────┼────────────────┼─────────────────────┼───────────────────────┘
          │                │                     │
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    CLIP GENERATION & EXPORT                            │
│  ┌────────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │ Draft Highlight    │  │ Final Highlight   │  │ Editor Review UI   │  │
│  │ (xuất sớm khi     │  │ (xuất sau khi     │  │ (adjust pre/post-  │  │
│  │  peak detected)    │  │  event CLOSED)     │  │  roll, accept/     │  │
│  │                    │  │                    │  │  reject, feedback)  │  │
│  └────────────────────┘  └──────────────────┘  └────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    FEEDBACK LOOP                                  │   │
│  │  Editor corrections → Update thresholds, weights, offsets         │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         STORAGE                                        │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ PostgreSQL │  │ Local Disk   │  │ S3/R2        │  │ SQLite      │  │
│  │ (metadata, │  │ (raw video   │  │ (exported    │  │ (MVP simple │  │
│  │  events,   │  │  segments,   │  │  clips,      │  │  option)    │  │
│  │  feedback) │  │  temp buffer)│  │  archive)    │  │             │  │
│  └────────────┘  └──────────────┘  └──────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Nguyên tắc kiến trúc

1. **Per-Stream Worker**: Mỗi livestream = 1 worker process độc lập. Worker crash không ảnh hưởng stream khác.
2. **Local-First Processing**: STT, audio DSP, chat analysis chạy local trên CPU. Không phụ thuộc network cho real-time path.
3. **LLM-as-Refinement**: LLM chỉ được gọi khi event candidate đã được detect bởi signal layer. Không bao giờ gọi LLM liên tục theo thời gian.
4. **Buffer-Backed Extraction**: Mọi extraction dựa trên circular buffer. Buffer đủ lớn để look-back tìm trigger.
5. **Event-Driven Architecture**: Components giao tiếp qua event/message, không polling.
6. **Graceful Degradation**: Nếu 1 signal source fail (ví dụ: STT chậm), hệ thống vẫn detect được highlight từ các signal còn lại.

### Tech Stack (MVP)

| Component | Technology | Lý do |
|---|---|---|
| **Language** | Python 3.11+ | Ecosystem AI/ML tốt nhất, thư viện STT/audio phong phú |
| **STT** | faster-whisper (local) hoặc PhoWhisper | Miễn phí, chạy CPU, hỗ trợ tiếng Việt |
| **Audio DSP** | librosa + scipy | Miễn phí, mature, đủ cho energy/pitch analysis |
| **Message Queue** | Redis Streams (MVP) | Nhẹ, đơn giản, đủ cho 1–3 stream |
| **Database** | SQLite (MVP) → PostgreSQL (scale) | Zero-config cho MVP, migrate dễ |
| **Video Processing** | FFmpeg | Industry standard, miễn phí |
| **LLM** | OpenRouter API (model rẻ nhất phù hợp) | Linh hoạt chọn model, pay-per-use |
| **Web UI** | FastAPI + HTMX hoặc simple React | Editor review interface |
| **Storage** | Local disk (MVP) → Cloudflare R2 (scale) | R2 free tier 10GB/tháng |

---

## PHẦN 1 — Livestream Ingestion

### 1.1 Data Acquisition

#### Video Stream

| Phương án | Mô tả | Ưu điểm | Nhược điểm | Khuyến nghị |
|---|---|---|---|---|
| **HLS Pull (yt-dlp/streamlink)** | Dùng yt-dlp hoặc streamlink pull HLS manifest → download TS segments | Đơn giản, mature tools, hỗ trợ nhiều platform | Latency 5–15s (do HLS segment duration), có thể bị platform block | ✅ MVP |
| **FLV/WebSocket (TikTok Live Connector)** | Dùng thư viện unofficial kết nối trực tiếp WebSocket stream | Latency thấp hơn (~2–5s), nhận raw FLV stream | Unofficial, dễ bị break khi TikTok đổi API, cần maintain | ✅ Backup |
| **RTMP Relay** | Setup RTMP server, streamer push stream vào server mình | Full control, latency thấp nhất | Yêu cầu streamer config lại OBS, không khả thi cho "theo dõi" | ❌ Không phù hợp |
| **Platform SDK/Official API** | Dùng TikTok official API cho live | Ổn định, được support | TikTok chưa cung cấp public API cho live stream access | ❌ Không available |

**Quyết định MVP:** Dùng **yt-dlp** hoặc **streamlink** để pull HLS stream. Latency 5–15 giây chấp nhận được vì highlight extraction không cần sub-second latency. Song song thử nghiệm **TikTok-Live-Connector** (Node.js) cho latency thấp hơn.

**Quy trình pull stream:**
```
yt-dlp --live-from-start --no-part -o "pipe:" <tiktok_live_url>
  │
  ▼
FFmpeg (demux, extract audio, transcode nếu cần)
  │
  ├──▶ Video segments (HLS .ts hoặc .mp4 chunks, 2s mỗi segment)
  └──▶ Audio PCM (16kHz mono, cho STT)
```

#### Audio Stream

Audio được tách từ video container bằng FFmpeg, không cần stream riêng.

```
FFmpeg pipeline:
  Input: HLS/FLV stream
  Output 1: Video segments → Video Buffer
  Output 2: Audio PCM 16kHz mono → Audio Buffer + STT Engine
```

**Thông số audio cho STT:**
- Sample rate: 16,000 Hz
- Channels: Mono
- Format: 16-bit PCM (WAV) hoặc Float32
- Chunk size: 5 giây (chunk cho Whisper processing)

#### Chat/Comment Realtime

| Phương án | Mô tả | Ưu điểm | Nhược điểm |
|---|---|---|---|
| **TikTok-Live-Connector** | WebSocket connection tới TikTok Live, nhận chat events realtime | Latency thấp (~1–2s), nhận được gift/like/share events | Unofficial, có thể bị block |
| **Screen scraping** | Capture chat overlay từ stream video | Không cần API, hoạt động với mọi platform | Accuracy thấp, cần OCR, latency cao |
| **Manual input** | Editor nhập note thủ công | 100% accurate | Không scalable, không realtime |

**Quyết định MVP:** Dùng **TikTok-Live-Connector** cho chat. Nếu bị block, fallback sang "no chat signal" mode — hệ thống vẫn hoạt động được từ audio/transcript signal.

**Chat event schema:**
```
ChatMessage {
  message_id: string
  user_id: string
  username: string
  content: string
  timestamp_utc: datetime     // UTC từ TikTok server
  event_type: enum {
    COMMENT,
    GIFT,
    LIKE,
    SHARE,
    FOLLOW,
    SUBSCRIBER
  }
  gift_value: float?          // giá trị gift nếu là GIFT event
  raw_data: json              // raw event data cho debug
}
```

### 1.2 Recorder Architecture

#### Per-Stream Worker Design

```
┌────────────────────────── Stream Worker (1 per livestream) ──────────────┐
│                                                                          │
│  ┌─────────────────┐       ┌──────────────────┐                         │
│  │ StreamRecorder   │       │ ChatCollector     │                        │
│  │                  │       │                   │                        │
│  │ - yt-dlp/        │       │ - TikTok-Live-    │                        │
│  │   streamlink     │       │   Connector       │                        │
│  │ - FFmpeg demux   │       │ - WebSocket       │                        │
│  │ - Health monitor │       │ - Reconnect logic │                        │
│  └────────┬─────────┘       └─────────┬─────────┘                        │
│           │                           │                                  │
│           ▼                           ▼                                  │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    Circular Buffer Manager                       │    │
│  │  Video Ring │ Audio Ring │ Transcript Ring │ Chat Ring            │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│           │                                                              │
│           ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    Processing Pipeline                           │    │
│  │  STT → Audio DSP → Chat Analyzer → Signal Aggregator → Events   │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────┐                                                    │
│  │ Worker Supervisor │  ← Monitors health, restarts on failure          │
│  └──────────────────┘                                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Reconnect Strategy

```
Reconnection State Machine:

  CONNECTED ──(stream error/timeout)──▶ RECONNECTING
      ▲                                       │
      │                                       ▼
      │                              ┌─────────────────┐
      │                              │ Backoff Logic:   │
      │                              │ Attempt 1: 1s   │
      │                              │ Attempt 2: 2s   │
      │                              │ Attempt 3: 4s   │
      │                              │ Attempt 4: 8s   │
      │                              │ Attempt 5: 16s  │
      │                              │ Max: 30s        │
      │                              └────────┬────────┘
      │                                       │
      └───────(reconnected)───────────────────┘
                                              │
                              (10 failures in 5 min)
                                              │
                                              ▼
                                        STREAM_ENDED
                                   (notify, save buffer,
                                    process remaining events)
```

**Xử lý stream ngắt đột ngột:**

1. **Detect:** Timeout 10 giây không nhận được data mới.
2. **Buffer preservation:** Flush toàn bộ circular buffer ra disk trước khi reconnect.
3. **Gap marker:** Ghi lại khoảng gap (start_gap_pts, end_gap_pts) vào metadata.
4. **Resume:** Khi reconnect thành công, tiếp tục ghi vào buffer với gap marker.
5. **Impact on highlight:** Nếu event candidate đang ACTIVE mà bị gap > 5s, đánh dấu `quality: degraded`.

**Xử lý quality thay đổi:**

```
Quality Monitor:
  - Check bitrate mỗi 5 giây (từ FFmpeg stats)
  - Nếu bitrate drop > 50%:
    1. Log warning
    2. Giảm video analysis (skip frame analysis, chỉ giữ audio)
    3. Đánh dấu segment quality = "low"
  - Nếu resolution thay đổi:
    1. Restart FFmpeg pipeline với params mới
    2. Ghi marker vào buffer tại điểm thay đổi
```

### 1.3 Circular Buffer Design

#### Buffer Dimensions

| Buffer | Độ dài | Format | Kích thước ước lượng | Index method |
|---|---|---|---|---|
| **Video** | 10 phút | H.264 TS segments (2s mỗi segment) | ~300 MB (1080p) / ~100 MB (720p) | PTS timestamp |
| **Audio** | 10 phút | PCM 16kHz mono 16-bit | ~19 MB | Sample position → PTS mapping |
| **Transcript** | 15 phút | JSON (word-level timestamps) | ~500 KB | Word start_pts / end_pts |
| **Chat** | 15 phút | JSON (messages + metadata) | ~2 MB (busy chat) | Adjusted PTS |

**Lý do chọn 10 phút cho video/audio:**
- Phần lớn highlight event kéo dài 30s–5 phút.
- Worst case: trigger nằm cách peak ~5 phút. Với 10 phút buffer, luôn đủ look-back.
- Memory: ~300 MB/stream là chấp nhận được (1–3 stream = 300–900 MB).

**Lý do transcript/chat buffer dài hơn (15 phút):**
- Transcript và chat rất nhẹ (< 3 MB).
- Cần look-back xa hơn video cho context understanding.
- LLM gate cần nhiều transcript context hơn để quyết định boundary.

#### Cơ chế hoạt động

```
Circular Buffer hoạt động theo segment-based ring:

Video Buffer (10 min = 300 segments × 2s):
  ┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐
  │ 0 │ 1 │ 2 │...│297│298│299│ 0'│ 1'│...│  ← ghi đè khi đầy
  └───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘
   ▲write_head                    ▲oldest

Khi write_head đuổi kịp oldest:
  - Segment cũ nhất bị ghi đè
  - TRƯỚC KHI ghi đè: check xem segment đó có được reference bởi
    event candidate nào không
  - Nếu CÓ: copy segment đó ra "pinned storage" trước khi ghi đè
  - Nếu KHÔNG: ghi đè bình thường
```

**Pinned Storage — Khi cần mở rộng buffer:**

Khi một event candidate được mở (OPENING state), hệ thống "pin" các segment liên quan:
- Pin segment từ estimated_trigger_pts đến hiện tại
- Pinned segments không bị ghi đè, được copy ra disk
- Khi event CLOSED hoặc bị hủy: unpin và cho phép ghi đè lại

**Trigger lưu buffer vĩnh viễn:**

Buffer được flush ra persistent storage khi:
1. Event candidate chuyển sang CLOSED → segments từ start đến end được lưu.
2. Stream kết thúc → toàn bộ buffer hiện tại được flush.
3. Buffer underrun sắp xảy ra (event candidate reference segment sắp bị ghi đè).
4. Manual trigger từ editor UI.

**Phối hợp với highlight detection pipeline:**

```
Buffer ←──reads──── Signal Aggregator (read-only access)
Buffer ←──reads──── Dynamic Context Expansion (look-back/forward)
Buffer ←──reads──── Clip Generator (extract video segments)
Buffer ←──writes─── Stream Recorder (continuous write)
Buffer ←──pins───── Event State Machine (pin segments for active events)
```

---

## PHẦN 2 — Realtime Processing Pipeline

### 2.1 Pipeline Components

#### 2.1.1 Speech-to-Text (STT)

**Model:** faster-whisper (CTranslate2) với model `medium` hoặc PhoWhisper-medium

**Chiến lược chunk:**
```
Audio Stream (16kHz mono)
  │
  ├──▶ Chunker: 5 giây mỗi chunk, overlap 0.5 giây
  │    (overlap để tránh cắt giữa từ)
  │
  ▼
faster-whisper inference (CPU)
  │
  ▼
Output: {
  text: "xin chào các bạn hôm nay chúng ta sẽ...",
  segments: [
    { start: 0.0, end: 1.2, text: "xin chào các bạn", confidence: 0.92 },
    { start: 1.2, end: 2.8, text: "hôm nay chúng ta sẽ", confidence: 0.88 }
  ],
  language: "vi",
  chunk_start_pts: 12345.0  // absolute PTS of chunk start
}
```

**Latency target:** < 3 giây per chunk (5s audio → 3s processing trên CPU i7/Ryzen 7)

**Fallback khi CPU overloaded:**
- Giảm model size: medium → small → base
- Tăng chunk size: 5s → 10s (giảm overhead, tăng latency)
- Skip 1 in N chunks (giảm accuracy, giữ được realtime)

#### 2.1.2 Audio Analysis (DSP — Không cần AI)

Toàn bộ audio analysis dùng DSP thuần, chạy trên CPU, miễn phí.

```
Audio Chunk (5s, 16kHz mono)
  │
  ├──▶ Energy Analyzer
  │    - RMS energy per 100ms frame
  │    - Output: energy_curve[50 frames]
  │    - Detect: spike khi energy > 2x rolling_mean (window 30s)
  │
  ├──▶ Pitch Analyzer
  │    - F0 estimation per 100ms frame (autocorrelation method)
  │    - Output: pitch_curve[50 frames]
  │    - Detect: pitch spike (excitement), pitch drop (sadness)
  │
  ├──▶ Silence Detector
  │    - RMS < threshold (calibrated per stream) cho > 500ms
  │    - Output: silence_regions[]
  │    - Pattern: silence → burst = setup → punchline
  │
  ├──▶ Speaking Rate Estimator
  │    - Syllable count / duration (từ STT word timestamps)
  │    - Output: syllables_per_second
  │    - Detect: nói nhanh (> 5 syl/s) = excitement
  │              nói chậm (< 2 syl/s) = dramatic pause
  │
  ├──▶ Multi-Speaker Detector
  │    - Energy variance analysis: nhiều nguồn = energy pattern phức tạp
  │    - Overlap detection: khi 2+ voices cùng lúc
  │    - Output: overlap_ratio (0.0–1.0)
  │    - Detect: overlap > 0.3 = argument/heated discussion
  │
  └──▶ Laughter Detector
       - Spectral feature matching: laughter có pattern đặc trưng
         (periodic bursts, high frequency energy)
       - Simple classifier: SVM/Random Forest trained trên laughter dataset
       - Output: laughter_probability per 500ms frame
       - Detect: probability > 0.7 = laughter event
```

**Latency target:** < 100ms per 5s chunk (DSP rất nhanh)

#### 2.1.3 Chat Analysis (Rule-based — Không cần AI)

```
Chat Message Stream
  │
  ├──▶ Volume Monitor
  │    - Count messages per 5-second window
  │    - Rolling baseline: mean messages/5s over last 5 minutes
  │    - Spike: current > 3x baseline
  │    - Output: volume_spike_score (0.0–1.0)
  │
  ├──▶ Emoji/Reaction Pattern Detector
  │    - Count emotion-related emojis per 5s window
  │    - Categories:
  │      FUNNY: 😂🤣💀😆 → laugh_emoji_score
  │      SHOCK: 😱😨🤯 → shock_emoji_score
  │      LOVE:  ❤️😍🥰 → love_emoji_score
  │      SAD:   😢😭💔 → sad_emoji_score
  │    - Normalize: emoji_count / total_messages in window
  │
  ├──▶ Keyword Cluster Detector
  │    - Predefined keyword sets (configurable):
  │      HYPE: ["gg", "clutch", "pro", "slay", "queen"]
  │      SHOCK: ["ôi", "trời ơi", "wth", "omg", "what"]
  │      DRAMA: ["drama", "beef", "cancel", "exposed"]
  │    - Detect: khi >= 3 messages trong 5s chứa cùng keyword cluster
  │    - Output: keyword_cluster_score per category
  │
  ├──▶ Gift/Donation Detector
  │    - event_type == GIFT hoặc SUBSCRIBER
  │    - Score based on gift_value (normalized)
  │    - Big gift (> threshold) = highlight signal
  │
  └──▶ Spam Filter
       - Loại bỏ bot messages (repeat exact same text > 3 lần)
       - Loại bỏ quá nhiều message từ cùng user trong 5s
       - Output: filtered message stream
```

**Latency target:** < 50ms (pure string/count operations)

#### 2.1.4 Video Analysis (Phase 2 — Deferred for MVP)

> **Lý do defer:** Video analysis cần GPU hoặc model nặng, không phù hợp budget MVP. Audio + transcript + chat đủ để detect phần lớn highlights. Video analysis sẽ được thêm ở Phase 2.

Khi triển khai (Phase 2), bao gồm:
- **Scene change detection:** Histogram diff giữa frames liên tiếp (CPU, OpenCV)
- **Motion detection:** Optical flow magnitude (CPU, OpenCV)
- **Face emotion:** Lightweight model (MobileFaceNet + emotion classifier)

MVP fallback: Chỉ dùng **scene change detection** bằng OpenCV (CPU) nếu cần. Đây là thuật toán DSP thuần, không cần AI model.

#### 2.1.5 Event Detection — Signal Aggregation

```
Mỗi 1 giây, Signal Aggregator nhận signals từ tất cả sources:

SignalSnapshot {
  pts: float                    // master clock timestamp
  
  // Audio signals
  audio_energy: float           // 0.0–1.0 normalized
  audio_energy_spike: bool      // true nếu > 2x baseline
  pitch_deviation: float        // 0.0–1.0 from baseline
  silence_before: float         // seconds of silence trước đó
  speaking_rate: float          // syllables/second
  speaker_overlap: float        // 0.0–1.0
  laughter_prob: float          // 0.0–1.0
  
  // Transcript signals
  transcript_text: string       // text mới nhất
  sentiment_shift: float        // -1.0 to 1.0 (negative=bad, positive=good)
  keyword_triggered: string[]   // keywords detected
  sentence_rate: float          // sentences per 10s (dồn dập = high)
  
  // Chat signals  
  chat_volume_spike: float      // 0.0–1.0
  chat_emoji_scores: {          // per-category emoji scores
    funny: float,
    shock: float,
    love: float,
    sad: float
  }
  chat_keyword_cluster: string? // cluster name nếu detected
  gift_event: GiftEvent?        // gift/donation nếu có
}
```

#### 2.1.6 Highlight Scoring

**Composite Score tính mỗi 1 giây:**

```
excitement_score = (
    0.25 * audio_energy_spike_score +
    0.20 * laughter_prob +
    0.15 * chat_volume_spike +
    0.15 * speaking_rate_score +
    0.10 * pitch_deviation +
    0.10 * chat_emoji_dominant_score +
    0.05 * speaker_overlap
)

// Bonus multipliers
if silence_before > 2.0 AND audio_energy_spike:
    excitement_score *= 1.5  // setup → punchline pattern

if keyword_triggered is not empty:
    excitement_score *= 1.3  // keyword boost

if gift_event and gift_event.value > big_gift_threshold:
    excitement_score *= 1.4  // big donation boost
```

**Threshold để trigger event:**
- `excitement_score > 0.6` → Mở event candidate (OPENING)
- `excitement_score > 0.8` → Confirm event (ACTIVE)
- Threshold tự calibrate dựa trên rolling percentile (top 5% scores trong 10 phút qua)

### 2.2 Data Flow Diagram

```
                    ┌──────────────────────┐
                    │   TikTok Live URL    │
                    └──────────┬───────────┘
                               │
               ┌───────────────┼───────────────┐
               ▼                               ▼
    ┌──────────────────┐            ┌────────────────────┐
    │  yt-dlp/         │            │  TikTok-Live-      │
    │  streamlink      │            │  Connector          │
    │  (HLS pull)      │            │  (WebSocket)        │
    └────────┬─────────┘            └─────────┬──────────┘
             │                                │
             ▼                                ▼
    ┌──────────────────┐            ┌────────────────────┐
    │  FFmpeg Demux    │            │  Chat Message       │
    │  ├─ Video .ts    │            │  Parser             │
    │  └─ Audio PCM    │            └─────────┬──────────┘
    └───┬──────┬───────┘                      │
        │      │                              │
        ▼      ▼                              ▼
    ┌──────┐ ┌──────┐                 ┌─────────────┐
    │Video │ │Audio │                 │ Chat Buffer │
    │Buffer│ │Buffer│                 │ (15 min)    │
    │(10m) │ │(10m) │                 └──────┬──────┘
    └──┬───┘ └──┬───┘                        │
       │        │                            │
       │        ├──────────────┐             │
       │        │              │             │
       │        ▼              ▼             ▼
       │  ┌──────────┐  ┌──────────┐  ┌──────────────┐
       │  │ STT      │  │ Audio    │  │ Chat         │
       │  │ Engine   │  │ DSP      │  │ Analyzer     │
       │  │(Whisper) │  │(energy,  │  │(volume,emoji │
       │  │          │  │ pitch,   │  │ keyword,gift)│
       │  │          │  │ silence, │  │              │
       │  │          │  │ laugh)   │  │              │
       │  └────┬─────┘  └────┬─────┘  └──────┬───────┘
       │       │              │               │
       │       ▼              │               │
       │  ┌──────────┐       │               │
       │  │Transcript│       │               │
       │  │Buffer    │       │               │
       │  │(15 min)  │       │               │
       │  └────┬─────┘       │               │
       │       │              │               │
       │       ▼              ▼               ▼
       │  ┌──────────────────────────────────────────┐
       │  │         TIMESTAMP ALIGNMENT              │
       │  │    (all signals → Master PTS clock)      │
       │  └──────────────────┬───────────────────────┘
       │                     │
       │                     ▼
       │  ┌──────────────────────────────────────────┐
       │  │         SIGNAL AGGREGATOR                │
       │  │  (combine signals → SignalSnapshot/1s)   │
       │  └──────────────────┬───────────────────────┘
       │                     │
       │                     ▼
       │  ┌──────────────────────────────────────────┐
       │  │      HIGHLIGHT EXTRACTION ENGINE         │
       │  │  Event Detector → State Machine →        │
       │  │  Context Expansion → Boundary Detection  │
       │  └──────────────────┬───────────────────────┘
       │                     │
       │                     ▼
       │               ┌───────────┐
       │               │ LLM Gate  │  ← gọi LLM chỉ khi
       │               │(OpenRouter│     event cần refine
       │               │ < 5x/giờ) │     boundary
       │               └─────┬─────┘
       │                     │
       │                     ▼
       │  ┌──────────────────────────────────────────┐
       │  │      HIGHLIGHT CANDIDATE OUTPUT          │
       │  │  { event_id, start_pts, end_pts,         │
       │  │    score, type, status, signals }         │
       │  └──────────────────┬───────────────────────┘
       │                     │
       ├─────────────────────┤
       │                     │
       ▼                     ▼
  ┌──────────┐     ┌──────────────────┐
  │ Clip     │     │  Editor Review   │
  │ Generator│     │  UI (FastAPI +   │
  │ (FFmpeg) │     │  HTMX)           │
  └────┬─────┘     └────────┬─────────┘
       │                    │
       ▼                    ▼
  ┌──────────┐     ┌──────────────────┐
  │ Exported │     │  Feedback Loop   │
  │ Clips    │     │  (update weights │
  │ (.mp4)   │     │   & thresholds)  │
  └──────────┘     └──────────────────┘
```

### 2.3 Latency Budget

Target tổng: **< 10 giây** từ peak event đến highlight candidate được tạo.

| Stage | Latency Target | Ghi chú |
|---|---|---|
| **HLS Segment Delay** | 4–8s | Do HLS protocol, segment duration 2–4s + propagation |
| **FFmpeg Demux** | < 200ms | Real-time pipe, gần như instant |
| **Audio Chunk Assembly** | 5s | Đợi đủ 5s audio cho STT chunk |
| **STT Inference** | 2–3s | Whisper medium trên CPU (5s audio) |
| **Audio DSP** | < 100ms | Pure signal processing |
| **Chat Analysis** | < 50ms | String operations |
| **Signal Aggregation** | < 50ms | Combine + score calculation |
| **Event Detection** | < 100ms | Threshold check + state transition |
| **TỔNG (worst case)** | ~12–16s | Bao gồm HLS delay |
| **TỔNG (excl. HLS)** | ~7–8s | Nếu dùng WebSocket/FLV connection |

> **Note:** HLS delay 4–8s là inherent protocol delay, không thể giảm. Nếu cần latency thấp hơn, phải dùng FLV/WebSocket connection (TikTok-Live-Connector).

> **Tradeoff:** Chấp nhận 12–16s total delay. Lý do: highlight sẽ được editor review trước khi publish, nên 16s delay không ảnh hưởng end-user experience. Clip vẫn được tạo "near-realtime" so với livestream duration (giờ).

---

## PHẦN 3 — Highlight Extraction Engine (Cốt lõi sản phẩm)

### 3A — Highlight Discovery

#### Event Phase Detection

Mỗi highlight hoàn chỉnh gồm 5 phase. Dưới đây là cách phát hiện từng phase bằng signals:

##### Phase 1: TRIGGER — Sự kiện kích hoạt

| Signal Source | Cách detect | Score | Trọng số |
|---|---|---|---|
| **Transcript** | Keyword match: câu hỏi bất ngờ ("thật hả?", "bao nhiêu?"), tên người nổi tiếng, số tiền lớn (regex match `\d+[kmKM]\b`, `\d+ tỷ`, `\d+ triệu`) | Keyword relevance score 0.0–1.0 (dựa trên predefined keyword importance) | 0.30 |
| **Audio** | Silence > 2s trước một câu nói = dramatic setup. Energy shift từ low → medium = sắp có gì đó | silence_duration / 5.0 (cap 1.0) | 0.20 |
| **Chat** | Gift/donation event. Hoặc sudden topic keyword cluster | gift_score hoặc keyword_cluster_score | 0.25 |
| **Transcript** | Sentiment shift: detect khi 3 câu liên tiếp có sentiment thay đổi > 0.5 (dùng simple VADER-like rules cho tiếng Việt hoặc keyword-based sentiment) | abs(sentiment_delta) / max_delta | 0.25 |

**Cách normalize score:** Mỗi signal score được normalize về 0.0–1.0 bằng min-max scaling dựa trên rolling baseline (5 phút gần nhất). Score 0.0 = bằng baseline, score 1.0 = max observed trong 5 phút.

##### Phase 2: BUILD-UP — Tension tăng dần

| Signal Source | Cách detect | Score |
|---|---|---|
| **Audio** | Energy tăng monotonically qua 3+ snapshots liên tiếp | Gradient của energy_curve (slope > 0 = building) |
| **Speaking rate** | Nói nhanh dần: syllable rate tăng qua 3+ snapshots | Delta speaking_rate / baseline_rate |
| **Chat** | Volume tăng dần (không spike đột ngột, mà ramp up) | Gradient của chat_volume_curve |
| **Transcript** | Câu ngắn dồn dập: average sentence length giảm | 1.0 - (avg_sentence_length / baseline_sentence_length) |

**Detection rule:** Build-up detected khi >= 2 signals cùng cho thấy increasing trend qua >= 3 giây liên tiếp.

##### Phase 3: PEAK — Đỉnh điểm

| Signal Source | Cách detect | Score |
|---|---|---|
| **Audio** | Energy maximum cục bộ (local maxima trong 10s window) | energy / max_energy_in_session |
| **Audio** | Laughter burst: laughter_prob > 0.8 | laughter_prob |
| **Audio** | Scream/yell: energy > 3x baseline + high pitch | combined_score |
| **Chat** | Volume spike: messages/5s > 5x baseline | spike_magnitude / max_spike |
| **Chat** | Emoji storm: >= 70% messages chứa emotion emoji | emoji_ratio |
| **Transcript** | Exclamation/interjection: "ôi", "trời", "wow", "what" | keyword_match_score |

**Detection rule:** Peak confirmed khi composite excitement_score > PEAK_THRESHOLD (calibrated, default 0.75).

##### Phase 4: REACTION — Phản ứng

| Signal Source | Cách detect | Score |
|---|---|---|
| **Audio** | Sustained laughter (> 3s): laughter_prob > 0.6 liên tục | duration / max_expected_duration |
| **Chat** | Sustained high volume (> 10s sau peak) | sustained_ratio |
| **Transcript** | Commentary text: phrases like "trời ơi", "kinh quá", "điên thật" | phrase_match_score |
| **Audio** | Speaker overlap tăng (nhiều người nói cùng lúc = reaction) | overlap_ratio |

**Detection rule:** Reaction phase = period sau peak mà excitement_score vẫn > 0.4 (trên baseline nhưng dưới peak).

##### Phase 5: RESOLUTION — Kết thúc

| Signal Source | Cách detect | Score |
|---|---|---|
| **Audio** | Energy về baseline: rolling mean trở lại ± 20% baseline | 1.0 - (current_energy / peak_energy) |
| **Chat** | Volume về baseline: messages/5s trở lại ± 30% baseline | 1.0 - (current_volume / peak_volume) |
| **Transcript** | Topic shift: new topic keywords xuất hiện, không liên quan peak | topic_change_score |
| **Audio** | Speaking rate về bình thường | rate_normalization_score |
| **Silence** | Pause > 3s sau reaction = natural break | is_pause boolean |

**Detection rule:** Resolution confirmed khi composite excitement_score giảm xuống < 0.3 và giữ < 0.3 trong >= 5 giây. Hoặc khi topic shift detected.

---

#### Signal Scoring Chi Tiết

**Cho mỗi signal, quy trình chuẩn hóa:**

```
1. RAW VALUE → lấy giá trị thô từ DSP/analysis
2. BASELINE → rolling mean/std từ 5 phút gần nhất
3. Z-SCORE → (raw - mean) / std
4. NORMALIZE → sigmoid(z-score) → 0.0–1.0
5. WEIGHT → nhân với trọng số theo phase đang detect

Ví dụ Audio Energy:
  raw_rms = 0.15
  baseline_mean = 0.05
  baseline_std = 0.02
  z_score = (0.15 - 0.05) / 0.02 = 5.0
  normalized = sigmoid(5.0) = 0.993  ← rất cao, likely spike
```

---

#### Phát hiện theo Content Type

| Content Type | Primary Signals | Secondary Signals | Ưu điểm detection | Nhược điểm |
|---|---|---|---|---|
| **Funny moments** | Laughter detection (audio), emoji storm 😂 (chat) | Silence→burst pattern, speaking rate spike | Laughter rất dễ detect bằng audio DSP | False positive từ background laughter hoặc laugh track |
| **Drama / Conflict** | Speaker overlap (argument), sentiment shift negative, chat keyword "drama" | Energy sustained high, speaking rate fast | Multi-signal correlation mạnh | Khó phân biệt drama thật vs đùa giỡn |
| **Shock moments** | Audio energy spike + silence trước đó, chat 😱 emoji storm | Pitch spike, transcript exclamation | Shock pattern rõ ràng (silence → burst) | Single-peak, dễ miss nếu streamer phản ứng nhẹ |
| **Arguments** | Speaker overlap > 0.5 kéo dài, energy sustained high | Chat volume spike, negative sentiment | Overlap detection khá chính xác | Cần speaker diarization tốt |
| **Emotional (cry)** | Pitch instability + low energy + silence gaps | Chat ❤️😢 emoji, keyword "khóc", "cảm động" | Emotional audio pattern unique | Low energy → dễ bị confused với boring segment |
| **Gaming highlights** | Audio energy spike (scream), chat "gg"/"clutch" | Speaking rate spike, excitement keywords | Chat signal rất mạnh cho gaming | Cần phân biệt game SFX vs streamer voice |
| **Podcast insights** | Sentiment shift, keyword trigger (số liệu, data), speaking rate slow→emphasis | Chat volume moderate spike, quote-like text | Transcript-driven, Whisper handles well | Subtle signals, cần tốt transcript quality |

---

### 3B — Story / Event Structure Detection

#### Event Boundary Detection Algorithm

```
Event Lifecycle:

  IDLE ──(trigger signal)──▶ STORY_START
    │                            │
    │                            ▼
    │                    ┌──────────────────┐
    │                    │ Check: composite  │
    │                    │ score > OPEN_THR  │
    │                    │ (default 0.5)     │
    │                    └────────┬─────────┘
    │                             │ yes
    │                             ▼
    │                      STORY_BUILDING
    │                             │
    │                    ┌────────┼────────┐
    │                    │        │        │
    │                    ▼        ▼        ▼
    │              Score tăng  Score ổn  Score giảm
    │              → continue  → wait   → check resolution
    │                    │        │        │
    │                    ▼        │        │
    │                    ├────────┘        │
    │                    ▼                 │
    │               STORY_CLIMAX          │
    │               (peak detected)       │
    │                    │                │
    │                    ▼                │
    │              STORY_REACTION         │
    │              (post-peak activity)   │
    │                    │                │
    │                    ├────────────────┘
    │                    ▼
    │              STORY_ENDING
    │              (score < CLOSE_THR cho > 5s)
    │                    │
    │                    ▼
    └──────────── IDLE (ready for next event)
```

**Story Start Detection:**

Tín hiệu mở event mới:
1. **Composite score vượt OPEN_THRESHOLD** (default 0.5, calibrated từ rolling percentile P80)
2. **Topic change trong transcript** (new keywords không liên quan topic trước)
3. **Silence gap > 3s** + audio energy shift (natural break trong conversation)
4. **External event** (gift/donation, raid notification)

**Phân biệt Continuation vs Noise:**

```
Khi event đang ACTIVE và score dao động:

IF score drops below ACTIVE_THRESHOLD (0.4) for < 3 seconds:
  → CONTINUATION (brief pause, vẫn cùng event)
  → Giữ event ACTIVE

IF score drops below ACTIVE_THRESHOLD for 3–8 seconds:
  → UNCERTAIN: check transcript cho topic continuity
  → Nếu cùng topic → CONTINUATION
  → Nếu khác topic → RESOLUTION CANDIDATE

IF score drops below CLOSE_THRESHOLD (0.25) for > 5 seconds:
  → RESOLUTION CONFIRMED → close event

IF score drops below ACTIVE_THRESHOLD nhưng có chat volume
   vẫn cao (viewer vẫn đang react):
  → CONTINUATION (streamer im nhưng chat vẫn sôi)
```

**Event Climax Detection:**

Peak = local maximum trong composite score curve:
```
is_peak = (
    score[t] > score[t-1] AND
    score[t] > score[t+1] AND
    score[t] > PEAK_THRESHOLD AND
    score[t] == max(score[t-5s : t+5s])  // highest in 10s window
)
```

Cho phép multiple peaks trong 1 event (handled ở Section 3G).

**Event Ending Detection:**

Resolution confirmed khi TẤT CẢ các điều kiện sau:
1. Composite score < CLOSE_THRESHOLD (0.25) liên tục >= 5 giây
2. Chat volume về baseline (< 1.5x baseline)
3. Không có keyword mới liên quan event
4. Hoặc: topic shift rõ ràng (streamer chuyển sang chủ đề khác)

---

### 3C — Dynamic Context Expansion

#### Thuật toán Look-Back (Tìm Trigger)

```
Khi peak detected tại PTS = T_peak:

1. INIT: search_start = T_peak
2. LOOK BACK theo step 1 giây:
   
   for t = T_peak - 1s, T_peak - 2s, ..., T_peak - MAX_LOOKBACK:
     
     snapshot = get_signal_snapshot(t)
     
     // Check STOP CONDITIONS (từ trên xuống, ưu tiên cao → thấp):
     
     a) HARD STOP: t < T_peak - MAX_LOOKBACK (default 300s = 5 phút)
        → Dừng. Trigger = t + 1s. Mark quality = "possibly_incomplete"
     
     b) BUFFER BOUNDARY: t < oldest_buffer_pts
        → Dừng. Trigger = oldest_buffer_pts. Mark quality = "buffer_limited"
     
     c) SILENCE GAP: silence_duration[t] > 3s AND t < T_peak - 5s
        → Trigger candidate. Natural break point.
        → Nhưng verify: check 5s trước silence xem có liên quan event không
        → Nếu KHÔNG liên quan → Dừng. Trigger = end of silence.
        → Nếu CÓ liên quan → Tiếp tục look back qua silence.
     
     d) TOPIC CHANGE: transcript topic tại t khác hoàn toàn so với peak topic
        → Dừng. Trigger = t + 1s (start of relevant topic)
     
     e) BASELINE ZONE: composite_score[t] < 0.15 liên tục >= 5s
        AND transcript topic khác peak topic
        → Dừng. Trigger = last point before score rose.
     
     f) PREVIOUS EVENT: t nằm trong range của event khác đã CLOSED
        → Dừng. Trigger = end of previous event.
   
3. OUTPUT: trigger_pts = best stop point found
```

#### Thuật toán Look-Forward (Tìm Resolution)

```
Khi peak detected tại PTS = T_peak:

1. INIT: Bắt đầu từ T_peak
2. LOOK FORWARD theo step 1 giây:
   
   for t = T_peak + 1s, T_peak + 2s, ...:
     
     // WAIT MODE: Vì stream đang live, cần đợi data thực tế
     // Không thể look forward vào tương lai → phải đợi real-time
     
     snapshot = wait_for_signal_snapshot(t)  // blocking wait
     
     // Check STOP CONDITIONS:
     
     a) HARD STOP: t > T_peak + MAX_LOOKFORWARD (default 120s = 2 phút)
        → Dừng. Resolution = t. Mark quality = "forced_close"
     
     b) RESOLUTION CONFIRMED:
        composite_score < CLOSE_THRESHOLD (0.25) liên tục >= 5s
        AND chat_volume < 1.5x baseline
        → Dừng. Resolution = t - 2s (trim trailing silence)
     
     c) TOPIC SHIFT: Transcript topic thay đổi rõ ràng
        → Dừng. Resolution = t - 1s (end of old topic)
     
     d) NEW EVENT TRIGGER: New event opened (composite > OPEN_THR)
        → Dừng current event. Resolution = t - 1s.
        → New event bắt đầu tại t.
     
     e) NATURAL BREAK: Silence > 5s + energy at baseline
        → Dừng. Resolution = start of silence.
   
3. OUTPUT: resolution_pts = stop point
```

#### Xử lý khi Trigger nằm ngoài Buffer

```
Trường hợp: Peak tại T_peak, look-back cần đến T_trigger,
             nhưng T_trigger < oldest_buffer_pts

Xử lý:
1. Ghi nhận: event.context_status = "PARTIAL"
2. Sử dụng transcript buffer (15 min, dài hơn video 10 min):
   - Nếu transcript còn → dùng transcript context để LLM generate
     summary text cho phần video bị mất
3. Clip bắt đầu từ oldest available video PTS
4. Thêm text overlay ở đầu clip: "[Context từ trước đó: ...]"
   dùng transcript text
5. Alert editor: "Highlight này có thể thiếu context đầu.
   Transcript context: [...]"
```

---

### 3D — Circular Buffer Strategy (Chi tiết)

#### Video Buffer

```
Cấu hình:
  - Độ dài: 10 phút (600 giây)
  - Format: HLS .ts segments, mỗi segment 2 giây
  - Số segments: 300
  - Kích thước mỗi segment: ~1 MB (1080p) / ~330 KB (720p)
  - Tổng kích thước: ~300 MB (1080p) / ~100 MB (720p)
  - Index: PTS timestamp → segment index mapping
  
Index structure:
  segment_index = {
    0: { pts_start: 1000.0, pts_end: 1002.0, path: "/buffer/v/seg_0.ts", pinned: false },
    1: { pts_start: 1002.0, pts_end: 1004.0, path: "/buffer/v/seg_1.ts", pinned: false },
    ...
  }
  
  // Lookup: given PTS, find segment
  find_segment(pts) → segment_index[floor((pts - base_pts) / 2.0) % 300]
```

#### Audio Buffer

```
Cấu hình:
  - Độ dài: 10 phút (600 giây)
  - Sample rate: 16,000 Hz
  - Format: 16-bit PCM mono
  - Kích thước: 600s × 16000 × 2 bytes = ~19.2 MB
  - Implementation: numpy circular array
  - Alignment: audio_pts = video_pts (synced by FFmpeg demux)
  
Lookup:
  sample_position = (target_pts - buffer_start_pts) * 16000
  audio_data = buffer[sample_position : sample_position + chunk_samples]
```

#### Transcript Buffer

```
Cấu hình:
  - Độ dài: 15 phút
  - Format: List of TranscriptSegment
  
TranscriptSegment {
  text: string
  words: [
    { word: "xin", start_pts: 1000.5, end_pts: 1000.8, confidence: 0.95 },
    { word: "chào", start_pts: 1000.8, end_pts: 1001.2, confidence: 0.92 },
    ...
  ]
  chunk_start_pts: float    // PTS khi chunk audio bắt đầu
  chunk_end_pts: float      // PTS khi chunk audio kết thúc
  language: string
  stt_model: string
}

Rolling update:
  - Mỗi 5s, thêm segment mới vào cuối
  - Xóa segment cũ hơn 15 phút (trừ khi pinned)
  - Word-level timestamps cho phép look-back chính xác
```

#### Chat Buffer

```
Cấu hình:
  - Độ dài: 15 phút
  - Format: List of ChatMessage (đã define ở Section 1.1)
  - Thêm field:
    adjusted_pts: float     // Chat timestamp đã bù lag (Section 4D)
  
Storage:
  - In-memory deque, max_length based on estimated max messages in 15 min
  - Estimated: ~1000 messages/phút (busy TikTok live) × 15 = 15,000 messages
  - Kích thước: ~2–5 MB
  
Lookup:
  messages_in_range(start_pts, end_pts) → filter by adjusted_pts
```

#### Buffer Expansion Logic

```
Khi nào mở rộng buffer:

1. EVENT CANDIDATE ACTIVE: 
   Nếu event đang ACTIVE và duration > 5 phút:
   → Pin tất cả segments từ trigger đến hiện tại
   → Segments pinned không bị ghi đè
   → Effectively buffer "mở rộng" cho event này

2. MULTIPLE CONCURRENT EVENTS:
   Nếu > 2 events đang ACTIVE cùng lúc:
   → Tăng buffer size tạm thời (thêm disk-backed overflow)
   → Alert: "High activity period, buffer extended"

3. BUFFER PRESSURE:
   Nếu pinned segments > 50% buffer:
   → Flush oldest pinned segments ra disk
   → Keep pointer to disk location cho retrieval
```

---

### 3E — Highlight Boundary Detection

#### Start Timestamp Algorithm

```
Sau khi Dynamic Context Expansion tìm được trigger_pts:

raw_start = trigger_pts

// Pre-roll: thêm khoảng yên tĩnh trước trigger để viewer có thời gian
// "settle in" trước khi event bắt đầu

pre_roll = calculate_pre_roll(event):
  
  // Tìm natural start point:
  // 1. Đầu câu chứa trigger word
  sentence_start = find_sentence_start_before(trigger_pts, transcript_buffer)
  
  // 2. Silence gap gần nhất trước trigger (natural break)
  last_silence_end = find_last_silence_end_before(trigger_pts, audio_buffer)
  
  // 3. Chọn point xa nhất (để có đủ context)
  natural_start = min(sentence_start, last_silence_end)
  
  // 4. Clamp: pre-roll tối thiểu 2s, tối đa 10s
  pre_roll_duration = trigger_pts - natural_start
  pre_roll_duration = clamp(pre_roll_duration, MIN_PRE_ROLL=2.0, MAX_PRE_ROLL=10.0)
  
  return pre_roll_duration

final_start = raw_start - pre_roll
```

#### End Timestamp Algorithm

```
Sau khi Dynamic Context Expansion tìm được resolution_pts:

raw_end = resolution_pts

// Post-roll: thêm khoảng sau resolution để không cắt đột ngột

post_roll = calculate_post_roll(event):
  
  // 1. Tìm natural end point sau resolution:
  // Cuối câu chứa comment/reaction cuối cùng
  sentence_end = find_sentence_end_after(resolution_pts, transcript_buffer)
  
  // 2. Silence gap gần nhất sau resolution
  next_silence_start = find_next_silence_start_after(resolution_pts, audio_buffer)
  
  // 3. Chọn point gần nhất (để không kéo dài quá)
  natural_end = min(sentence_end, next_silence_start)
  
  // 4. Clamp: post-roll tối thiểu 1s, tối đa 5s
  post_roll_duration = natural_end - resolution_pts
  post_roll_duration = clamp(post_roll_duration, MIN_POST_ROLL=1.0, MAX_POST_ROLL=5.0)
  
  return post_roll_duration

final_end = raw_end + post_roll
```

**Pre-roll / Post-roll defaults:**

| Parameter | Mặc định | Min | Max | Lý do |
|---|---|---|---|---|
| Pre-roll | 3s | 2s | 10s | Cần đủ context nhưng không quá dài gây mất tập trung |
| Post-roll | 2s | 1s | 5s | Cho phép reaction tự nhiên kết thúc |

**Tránh cắt quá sớm:**
- Luôn bắt đầu tại **đầu câu** (sentence boundary) thay vì giữa câu
- Nếu trigger word nằm giữa câu, lùi về đầu câu đó

**Tránh cắt quá muộn:**
- Detect silence > 3s sau reaction cuối cùng → stop
- Detect topic change → stop
- Hard limit: post-roll không quá 5s sau last reaction signal

---

### 3F — Overlapping Event Resolution

#### Định nghĩa overlap types

```
Timeline:
  Event A:     |=====AAAAAAA=====|
  Event B:          |=====BBBBBBB=====|         → OVERLAP
  
  Event A:     |==========AAAAAAA==========|
  Event B:          |===BBBBB===|               → NESTED
  
  Event A:     |=====AAAA=====|
  Event B:                      |=====BBBB=====| → ADJACENT (gap < 5s)
                               ←gap→
```

#### Resolution Algorithm

```python
def resolve_events(events: List[Event]) -> List[Event]:
    # Sort by start_pts
    events.sort(key=lambda e: e.start_pts)
    
    resolved = []
    i = 0
    
    while i < len(events):
        current = events[i]
        
        # Check next events for overlap/adjacent
        j = i + 1
        while j < len(events):
            next_event = events[j]
            gap = next_event.start_pts - current.end_pts
            overlap = current.end_pts - next_event.start_pts
            
            if overlap > 0:  # OVERLAP hoặc NESTED
                if is_nested(current, next_event):
                    # NESTED: Event B nằm trong A
                    decision = resolve_nested(current, next_event)
                else:
                    # OVERLAP: Hai event giao nhau
                    decision = resolve_overlap(current, next_event)
                    
                if decision == MERGE:
                    current = merge_events(current, next_event)
                    j += 1
                    continue
                elif decision == KEEP_BOTH:
                    # Trim overlap: Event A end sớm hơn, Event B start muộn hơn
                    midpoint = (current.end_pts + next_event.start_pts) / 2
                    current.end_pts = midpoint
                    next_event.start_pts = midpoint
                    break
                elif decision == SUBORDINATE:
                    # next_event bị nuốt vào current, đánh dấu sub-event
                    current.sub_events.append(next_event)
                    j += 1
                    continue
                    
            elif gap < 5.0:  # ADJACENT (< 5s gap)
                decision = resolve_adjacent(current, next_event)
                if decision == MERGE:
                    current = merge_events(current, next_event)
                    j += 1
                    continue
                else:
                    break
            else:
                break  # No overlap, no adjacency
            
            j += 1
        
        resolved.append(current)
        i = j
    
    return resolved
```

#### Merge Strategy

| Tình huống | Điều kiện merge | Action |
|---|---|---|
| **OVERLAP + cùng topic** | Transcript topic similarity > 0.7 | MERGE: hợp thành 1 event, giữ peak score cao nhất |
| **OVERLAP + khác topic** | Topic similarity < 0.3 | KEEP_BOTH: trim tại midpoint |
| **OVERLAP + 1 score thấp hơn nhiều** | score_A / score_B > 3.0 | SUBORDINATE: event nhỏ thành sub-event |
| **NESTED + cùng topic** | Event B nằm hoàn toàn trong A | SUBORDINATE: B là sub-peak của A |
| **NESTED + khác topic** | Event B khác topic hoàn toàn | KEEP_BOTH: B là event riêng, A bị split quanh B |
| **ADJACENT + cùng topic** | Gap < 5s, cùng topic | MERGE |
| **ADJACENT + khác topic** | Gap < 5s, khác topic | KEEP_BOTH |

**Topic similarity:**
MVP dùng keyword overlap ratio: `|keywords_A ∩ keywords_B| / |keywords_A ∪ keywords_B|`
Phase 2: dùng embedding cosine similarity.

---

### 3G — Long Event Splitting

#### Multi-Peak Detection

```
Khi event duration > MAX_SINGLE_HIGHLIGHT (default 180s = 3 phút):

1. Tìm tất cả peaks trong event:
   peaks = find_local_maxima(score_curve[event.start : event.end],
                             min_prominence=0.3,  // peak phải nổi bật
                             min_distance=15s)     // min 15s giữa 2 peaks

2. Nếu len(peaks) >= 2:
   → Split thành micro-highlights, mỗi cái quanh 1 peak
   
3. Cho mỗi peak:
   micro_highlight = {
     center: peak.pts,
     start: find_valley_before(peak),   // valley = local minimum
     end: find_valley_after(peak),       // giữa 2 peaks liên tiếp
     score: peak.score
   }
   
4. Thêm pre-roll và post-roll cho mỗi micro-highlight
   (đảm bảo có context)

5. Nếu 2 micro-highlights quá gần nhau (gap < 5s):
   → Merge lại
```

#### Platform-Specific Duration Targets

| Platform | Target Duration | Splitting Strategy |
|---|---|---|
| **TikTok** | 15–60s | Aggressive split: mỗi peak = 1 clip. Pre-roll 2s, post-roll 1s. Ưu tiên high-energy, fast-paced. |
| **YouTube Shorts** | 15–60s | Tương tự TikTok. Có thể thêm title text overlay. |
| **Instagram Reels** | 15–90s | Cho phép dài hơn. Có thể merge 2 peaks gần nhau thành 1 reel. |
| **YouTube Clip** | 120–300s (2–5 phút) | Giữ nguyên event structure. Cho phép multiple peaks. Pre-roll dài hơn (5–10s). |
| **Full Highlight** | 300–600s (5–10 phút) | Toàn bộ event. Minimal trimming. |

**Splitting per platform:**
```
def split_for_platform(event, platform):
    if platform == "tiktok":
        target_duration = 45  # seconds
        max_duration = 60
        min_duration = 15
    elif platform == "youtube_shorts":
        target_duration = 45
        max_duration = 60
        min_duration = 15
    elif platform == "reels":
        target_duration = 60
        max_duration = 90
        min_duration = 15
    elif platform == "youtube_clip":
        target_duration = 180
        max_duration = 300
        min_duration = 60
    
    peaks = find_peaks(event)
    clips = []
    
    for peak in peaks:
        clip = extract_around_peak(peak, target_duration, max_duration)
        if clip.duration >= min_duration:
            clips.append(clip)
    
    return clips
```

---

### 3H — Highlight Ranking & Scoring

#### Scoring Formula

```
Highlight Score = w1*Drama + w2*Shock + w3*Emotion + w4*Curiosity + w5*Retention + w6*Virality
```

#### Component Definitions

| Component | Định nghĩa | Cách tính từ raw signals | Trọng số mặc định | Lý do |
|---|---|---|---|---|
| **Drama** | Mức độ conflict/tension trong event | `drama = 0.4*speaker_overlap_max + 0.3*sentiment_variance + 0.3*chat_negative_ratio` | 0.20 | Drama giữ viewer, tạo engagement |
| **Shock** | Mức độ bất ngờ, unexpected | `shock = 0.5*max(energy_spike_magnitude) + 0.3*silence_before_peak + 0.2*chat_shock_emoji_ratio` | 0.20 | Shock tạo shareability cao |
| **Emotion** | Cường độ cảm xúc (vui, buồn, xúc động) | `emotion = 0.4*laughter_duration + 0.3*pitch_variance + 0.3*chat_emotion_emoji_ratio` | 0.15 | Emotional content có retention tốt |
| **Curiosity** | Mức độ gây tò mò, hook viewer | `curiosity = 0.5*question_detected + 0.3*incomplete_statement + 0.2*keyword_trigger_score` | 0.15 | Curiosity tạo watch-through |
| **Retention** | Ước lượng viewer sẽ xem bao lâu | `retention = 0.4*build_up_quality + 0.3*pacing_score + 0.3*(1 - dead_air_ratio)` | 0.15 | Trực tiếp ảnh hưởng engagement metric |
| **Virality** | Khả năng được share/viral | `virality = 0.4*chat_volume_peak + 0.3*gift_total_value + 0.3*emoji_storm_intensity` | 0.15 | Revenue và growth driver |

#### Trọng số theo Content Type

| Component | Talkshow | Gaming | Entertainment | E-commerce |
|---|---|---|---|---|
| Drama | 0.25 | 0.10 | 0.25 | 0.05 |
| Shock | 0.15 | 0.30 | 0.20 | 0.15 |
| Emotion | 0.20 | 0.15 | 0.20 | 0.10 |
| Curiosity | 0.20 | 0.05 | 0.10 | 0.30 |
| Retention | 0.10 | 0.15 | 0.10 | 0.20 |
| Virality | 0.10 | 0.25 | 0.15 | 0.20 |

#### Học trọng số từ dữ liệu

```
Feedback Loop:
  1. Editor review highlight → accept/reject/modify
  2. Sau khi publish → thu thập engagement metrics (view, retention, share)
  3. Mỗi tuần: chạy simple linear regression:
     
     actual_performance = f(drama, shock, emotion, curiosity, retention, virality)
     
     → Update weights dựa trên regression coefficients
     → Smoothing: new_weight = 0.7 * old_weight + 0.3 * learned_weight
       (tránh weights thay đổi quá nhanh)
  
  4. Per content-type weights: group feedback by content type, learn riêng
```

---

### 3I — Human Feedback Loop

#### Feedback Schema

```sql
CREATE TABLE highlight_feedback (
  feedback_id       TEXT PRIMARY KEY,
  highlight_id      TEXT NOT NULL,
  stream_id         TEXT NOT NULL,
  editor_id         TEXT NOT NULL,
  
  -- AI proposal
  ai_start_pts      REAL NOT NULL,
  ai_end_pts        REAL NOT NULL,
  ai_score          REAL NOT NULL,
  ai_type           TEXT,          -- content type AI classified
  
  -- Editor decision
  action            TEXT NOT NULL,  -- 'ACCEPT', 'REJECT', 'MODIFY', 'SPLIT', 'MERGE'
  editor_start_pts  REAL,          -- null nếu REJECT
  editor_end_pts    REAL,          -- null nếu REJECT
  reject_reason     TEXT,          -- null nếu ACCEPT
  
  -- Computed deltas
  start_delta_sec   REAL,          -- editor_start - ai_start (negative = editor lùi lại)
  end_delta_sec     REAL,          -- editor_end - ai_end (positive = editor kéo dài)
  duration_delta    REAL,          -- editor_duration - ai_duration
  
  -- Engagement (filled later from published metrics)
  views             INTEGER,
  avg_watch_time    REAL,
  retention_3s      REAL,
  retention_10s     REAL,
  retention_30s     REAL,
  shares            INTEGER,
  
  -- Metadata
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  content_type      TEXT,
  stream_category   TEXT
);
```

#### Learning Pipeline

```
Mỗi ngày (batch job):

1. COLLECT: Lấy tất cả feedback trong 24h qua
2. ANALYZE:
   a) Start Offset:
      avg_start_delta = mean(start_delta_sec WHERE action = 'MODIFY')
      → Nếu editor thường lùi start lại 3s → tăng pre-roll default thêm 3s
      
   b) End Offset:
      avg_end_delta = mean(end_delta_sec WHERE action = 'MODIFY')
      → Nếu editor thường kéo dài thêm 2s → tăng post-roll default
      
   c) Accept Rate by Type:
      acceptance_rate = count(ACCEPT) / count(*) GROUP BY content_type
      → Content type nào acceptance rate < 50% → giảm sensitivity cho type đó
      
   d) Reject Analysis:
      common_reject_reasons → adjust thresholds
      
3. UPDATE:
   - Update pre_roll_default, post_roll_default
   - Update scoring weights (Section 3H)
   - Update thresholds per content type
   
4. VALIDATE:
   - Chạy updated model trên held-out set (20% recent data)
   - Nếu new model better → deploy
   - Nếu worse → rollback, alert
```

#### A/B Testing

```
Cơ chế A/B test đơn giản cho internal tool:

- Model A (current): 70% traffic (highlights)
- Model B (candidate): 30% traffic
- Metric: Editor acceptance rate
- Duration: 1 tuần
- Significance: Chi-square test, p < 0.05
- Auto-promote nếu B significantly better
- Auto-rollback nếu B significantly worse sau 3 ngày
```

#### Tránh Overfitting vào 1 Editor

```
Khi team có > 1 editor:
- Track feedback PER editor
- Compute "consensus" = average across editors (weighted by volume)
- Nếu 1 editor quá khác biệt (deviation > 2σ):
  → Flag review
  → Không update model chỉ dựa trên 1 editor
- Weight theo experience: editor có nhiều feedback hơn → weight cao hơn
```

---

### 3J — Evaluation Metrics

#### Output Metrics

| Metric | Cách đo | Frequency | Threshold Alert |
|---|---|---|---|
| **Highlight Precision** | `accepted / (accepted + rejected)` từ feedback table | Daily | < 60% → investigate |
| **Highlight Recall** | `ai_detected / (ai_detected + manually_added)` — editor thủ công thêm highlight mà AI miss | Daily | < 70% → urgent (miss > accept) |
| **Editor Acceptance Rate** | `accepted / total` per content type | Daily | < 50% per type → adjust type weights |
| **Average Edit Distance** | `mean(abs(start_delta) + abs(end_delta))` — editor phải sửa bao nhiêu giây | Daily | > 10s → boundary detection cần improve |

#### Engagement Metrics

| Metric | Cách đo | Frequency | Threshold |
|---|---|---|---|
| **Avg Watch Time** | Từ platform analytics API | Weekly | < 50% clip duration → clip quá dài hoặc boring intro |
| **Retention @3s** | % viewers vẫn xem tại 3s | Weekly | < 70% → hook kém, cần trim start |
| **Retention @10s** | % viewers tại 10s | Weekly | < 50% → build-up kém |
| **Retention @30s** | % viewers tại 30s | Weekly | < 30% → clip quá dài cho content |
| **Viral Rate** | `shares / views` | Weekly | Benchmark: > 2% = good |

#### Process Metrics

| Metric | Cách đo | Frequency | Threshold |
|---|---|---|---|
| **Detection Latency** | `highlight_candidate_created_at - peak_pts` | Per event | > 20s → pipeline bottleneck |
| **False Positive Rate** | `rejected / total` per content type | Daily | > 40% → threshold quá thấp |
| **Buffer Underrun Rate** | `count(context_status = "buffer_limited") / total` | Daily | > 5% → tăng buffer size |
| **Cold Start Miss Rate** | `missed_in_first_5min / total_in_first_5min` | Weekly | > 30% → cold start strategy cần improve |
| **STT Error Rate** | Sample random segments, manual verify | Weekly | WER > 30% cho tiếng Việt → switch model |

---

## PHẦN 4 — Hidden Complexity Solutions

### 4A — Cold Start Handling

#### 3-Tier Baseline Strategy

```
┌──────────────────────────────────────────────────────────────────┐
│                    STREAM TIMELINE                               │
│                                                                  │
│  0:00        1:00          5:00                          ∞       │
│  ├───────────┼──────────────┼────────────────────────────┤       │
│  │  Phase 0  │   Phase 1    │         Phase 2            │       │
│  │  GLOBAL   │   HYBRID     │       CALIBRATED           │       │
│  │  PRIOR    │   BLEND      │    (stream-specific)       │       │
│  └───────────┴──────────────┴────────────────────────────┘       │
│                                                                  │
│  Sensitivity: HIGH ──────────▶ NORMAL ──────────▶ CALIBRATED    │
│  False Pos:   HIGH ──────────▶ MEDIUM ──────────▶ LOW           │
│  Miss Rate:   LOW  ──────────▶ LOW    ──────────▶ LOWEST        │
└──────────────────────────────────────────────────────────────────┘
```

##### Phase 0 (0:00 → 1:00) — Global Prior Mode

```
Dùng baseline pre-computed từ lịch sử:

global_prior = {
  audio_energy_mean: 0.05,       // average across all recorded streams
  audio_energy_std: 0.02,
  chat_volume_mean: 8.0,         // messages per 5s
  chat_volume_std: 3.0,
  speaking_rate_mean: 3.5,       // syllables/s
  speaking_rate_std: 0.8,
  ...
}

Cách build:
1. Thu thập data từ 50+ livestream sessions (có thể từ recorded VODs)
2. Compute mean/std cho mỗi signal
3. Group by content_type nếu đủ data
4. Lưu vào file/DB, load khi start stream mới

Threshold adjustment:
  OPEN_THRESHOLD = global_open_threshold * 0.8  // giảm 20% → dễ trigger hơn
  PEAK_THRESHOLD = global_peak_threshold * 0.85
  // Ưu tiên recall: chấp nhận false positive cao hơn ở phase này
```

##### Phase 1 (1:00 → 5:00) — Hybrid Blend

```
blend_weight = (elapsed_seconds - 60) / (300 - 60)  // 0.0 tại 1:00, 1.0 tại 5:00

baseline = {
  mean: (1 - blend_weight) * global_prior.mean + blend_weight * stream_rolling.mean,
  std:  (1 - blend_weight) * global_prior.std  + blend_weight * stream_rolling.std
}

// Ở giây thứ 60: 100% global prior
// Ở giây thứ 180 (3 min): 50% global + 50% stream
// Ở giây thứ 300 (5 min): 100% stream data

Threshold:
  OPEN_THRESHOLD = lerp(phase0_threshold, calibrated_threshold, blend_weight)
```

##### Phase 2 (5:00+) — Calibrated Mode

```
Hoàn toàn dùng stream-specific rolling statistics:

baseline = rolling_stats(window=300s)  // 5 phút rolling window
  .mean, .std, .percentiles

Threshold:
  OPEN_THRESHOLD = percentile(composite_score, 80)   // top 20% = interesting
  PEAK_THRESHOLD = percentile(composite_score, 95)    // top 5% = peak
  CLOSE_THRESHOLD = percentile(composite_score, 30)   // bottom 30% = baseline

// Tự calibrate mỗi 30 giây
```

##### Recalibration khi Streamer đổi Activity

```
Activity Change Detection:
  - Monitor rolling 1-min stats vs rolling 5-min stats
  - Nếu |mean_1min - mean_5min| > 2 * std_5min:
    → Activity change detected
    → Reset calibration window
    → Temporarily blend: 50% old baseline + 50% new 1-min data
    → After 2 minutes: full recalibrate

Ví dụ:
  Streamer đang nói chuyện bình thường (low energy)
  → Đột ngột bắt đầu chơi game (high energy)
  → 1-min mean energy >> 5-min mean energy
  → Reset baseline, avoid flagging normal game energy as "spike"
```

---

### 4B — Multi-Source Audio Handling

#### Source Separation Architecture

```
Raw Audio (mixed)
  │
  ▼
┌────────────────────────────────────────┐
│ Source Separation Layer (Phase 2)      │
│                                        │
│ MVP: SKIP — process mixed audio       │
│ Phase 2: Demucs v4 (htdemucs_ft)      │
│                                        │
│ Output channels:                       │
│   ├─ vocals (streamer + guests)        │
│   ├─ music (game BGM, alerts)          │
│   └─ other (SFX, noise)               │
└───────────────────┬────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Vocals  │ │ Music   │ │ Other   │
   │→ STT    │ │→ Context│ │→ Ignore │
   │→ Emotion│ │  signal │ │         │
   │→ Diariz.│ │  only   │ │         │
   └─────────┘ └─────────┘ └─────────┘
```

**MVP Decision:** Skip source separation. Process mixed audio directly.

Lý do:
- Demucs cần GPU hoặc CPU rất mạnh (~4x realtime trên CPU)
- Budget không cho phép GPU
- TikTok live thường là 1 người nói + background nhẹ
- Whisper đã handle mixed audio khá tốt cho STT

**Phase 2 Plan (khi có GPU):**

| Model | Vai trò | GPU Requirement | Quality |
|---|---|---|---|
| **Demucs v4 (htdemucs_ft)** | Tách vocal/music/SFX | 2–4 GB VRAM | Tốt nhất cho music separation |
| **MDX-Net** | Alternative cho Demucs | 2 GB VRAM | Nhanh hơn, quality tương đương |
| **Simple bandpass filter** | Tách voice frequency (300Hz–3.4kHz) | CPU only | Nhanh, accuracy thấp |

#### Speaker Role Classification (Phase 2)

```
Khi có source separation:

1. Enrollment (đầu stream):
   - Lấy 30 giây đầu (streamer thường nói intro)
   - Extract voice embedding bằng ECAPA-TDNN hoặc Resemblyzer
   - Store: streamer_embedding = encode(first_30s_vocal)

2. Runtime classification:
   - Mỗi vocal segment: extract embedding
   - cosine_similarity(segment_embedding, streamer_embedding)
   - > 0.8 → PRIMARY (streamer)
   - < 0.5 → SECONDARY (guest/co-host)
   - 0.5–0.8 → UNCERTAIN

3. Signal weighting:
   - PRIMARY speaker signals: weight × 1.0
   - SECONDARY speaker signals: weight × 0.6
   - UNCERTAIN: weight × 0.8
```

**Lý do game audio chỉ là context signal:**

Game audio (SFX, music) phản ánh in-game events, không phải streamer emotion. Nếu đưa game explosion sound vào emotion score, sẽ tạo false positive. Game audio chỉ dùng để:
- Xác nhận in-game event (explosion = có thể clutch play)
- Detect game state change (victory fanfare, defeat music)
- KHÔNG dùng cho: energy scoring, emotion scoring, peak detection

---

### 4C — Multi-Signal Timestamp Alignment

#### Master Clock

**Quyết định: Video PTS là Master Clock.**

Lý do:
1. Video PTS là continuous và monotonic (đảm bảo bởi container format)
2. Video frames là đơn vị cuối cùng khi cắt clip (FFmpeg seek by PTS)
3. Mọi output (clip) đều dựa trên video timeline
4. Audio PTS đã sync với video PTS trong container (FFmpeg demux đảm bảo)

#### Alignment Procedures

```
┌─────────────────────────────────────────────────────────┐
│ Audio → Video Alignment                                 │
│                                                         │
│ FFmpeg demux đã đảm bảo audio PTS = video PTS         │
│ (cùng timebase từ container)                           │
│                                                         │
│ Verification: Mỗi 60s, check DTS/PTS offset            │
│ audio_offset = audio_pts - video_pts                    │
│ IF abs(audio_offset) > 100ms → log warning + re-sync   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Transcript → Audio Alignment                            │
│                                                         │
│ Khi submit audio chunk vào STT:                         │
│   chunk_start_pts = audio_buffer.current_pts            │
│                                                         │
│ STT output: segment.start = 1.5 (relative to chunk)     │
│ Absolute timestamp:                                      │
│   word_master_pts = chunk_start_pts + segment.start     │
│                                                         │
│ Công thức:                                               │
│   master_pts = chunk_start_pts + whisper_relative_ts    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Chat → Video Alignment                                  │
│                                                         │
│ Chat timestamp = UTC từ TikTok server                   │
│ Video PTS = relative to stream start                    │
│                                                         │
│ Cần biết: stream_start_utc (khi stream bắt đầu)        │
│                                                         │
│ Conversion:                                              │
│   chat_master_pts = chat_utc - stream_start_utc         │
│                     - platform_network_delay             │
│                     - chat_lag_compensation (Section 4D) │
│                                                         │
│ stream_start_utc: lấy từ stream metadata hoặc           │
│ calibrate bằng first chat message vs first video frame   │
└─────────────────────────────────────────────────────────┘
```

**Tại sao chat UTC không thể dùng trực tiếp:**
1. Chat UTC = thời gian TikTok server nhận message, không phải thời gian viewer nhìn thấy event.
2. Network delay: viewer xem stream → delay D giây → viewer gõ chat → chat server nhận. Chat timestamp đã bị shift bởi D.
3. Platform processing delay: TikTok server buffer và batch-deliver messages.
4. Clock difference: local machine clock có thể khác TikTok server clock.

#### Drift Detection

```
Mỗi 60 giây:

1. Collect: all signal sources' latest timestamps
2. Check pairwise drift:
   audio_video_drift = abs(audio_latest_pts - video_latest_pts)
   transcript_audio_drift = abs(transcript_latest_pts - audio_expected_pts)
   
3. Alert thresholds:
   - audio_video_drift > 200ms → WARNING, apply correction
   - audio_video_drift > 1000ms → ERROR, restart FFmpeg pipeline
   - transcript_audio_drift > 500ms → WARNING, likely STT lag
   
4. Correction:
   - Apply linear drift correction: 
     corrected_pts = raw_pts + drift_rate * elapsed_time
   - Record correction in SignalEvent.drift_correction_applied
```

#### SignalEvent Schema

```sql
CREATE TABLE signal_events (
  event_id            TEXT PRIMARY KEY,
  stream_id           TEXT NOT NULL,
  signal_type         TEXT NOT NULL,    -- 'audio_energy', 'chat_volume', 'transcript_keyword', etc.
  raw_timestamp       REAL NOT NULL,    -- original timestamp from source
  master_pts          REAL NOT NULL,    -- aligned to video PTS master clock
  value               REAL NOT NULL,    -- signal value (0.0–1.0 normalized)
  confidence          REAL DEFAULT 1.0, -- signal confidence
  drift_correction_ms REAL DEFAULT 0,   -- drift correction applied in ms
  source              TEXT NOT NULL,    -- 'audio_dsp', 'stt', 'chat', 'video'
  metadata            TEXT,             -- JSON additional data
  created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast range queries
CREATE INDEX idx_signal_events_stream_pts 
ON signal_events(stream_id, master_pts);

CREATE INDEX idx_signal_events_type_pts 
ON signal_events(signal_type, master_pts);
```

---

### 4D — Chat Signal Lag Compensation

#### Vấn đề

```
Timeline thực tế:
  T=0      T=3      T=5      T=8      T=10
  │        │        │        │        │
  ▼        ▼        ▼        ▼        ▼
  Event    Viewer   First    Chat     Chat
  happens  sees it  chat     peak     dies down
  on       (HLS     arrives  (most    
  stream   delay)            reacted)
  
Chat peak tại T=8, nhưng event xảy ra tại T=0.
Nếu correlate trực tiếp: system nghĩ event tại T=8 → SAI!
```

#### Platform Lag Pre-calibration

```
Phương pháp đo lag cho TikTok Live:

1. SYNTHETIC CALIBRATION (offline, setup 1 lần):
   a) Tạo stream test với known events (flash screen, beep sound)
      tại timestamp chính xác
   b) Quan sát chat reaction delay
   c) Measure: lag = chat_first_response_utc - event_utc
   d) Repeat 10 lần → compute mean, std

2. PASSIVE CALIBRATION (runtime, continuous):
   a) Detect audio energy spike (clear, unambiguous event)
   b) Detect subsequent chat volume spike
   c) Measure: lag = chat_spike_pts - audio_spike_pts
   d) Rolling average qua 10 events gần nhất

Default lag values (pre-calibrated):
  TikTok Live:  ~5s (range 3–8s)
  YouTube Live: ~6s (range 4–10s)
  Facebook Live: ~5s (range 3–8s)
```

#### Lag Compensation Formula

```
adjusted_pts = chat_master_pts - platform_lag

Trong đó:
  chat_master_pts = raw_chat_pts (đã align theo Section 4C)
  platform_lag = current_estimated_lag (rolling average)
```

#### Lag là Distribution, không phải Constant

```
Chat response sau 1 event không đến cùng lúc:

Chat Volume
  ▲
  │        ╭──╮
  │       ╱    ╲
  │      ╱      ╲
  │     ╱        ╲
  │    ╱          ╲──
  │───╱              ╲───
  └──┼────┼────┼────┼────▶ Time (seconds after event)
     2    4    6    8

Peak of distribution ≈ 5s → dùng peak, không dùng first message

Cách xác định peak:
  1. Bucket messages theo 1s windows
  2. Find window với max count
  3. peak_lag = window_with_max_count.center_time - event_time
```

#### Adaptive Lag Calibration

```
Mỗi 15 phút:

1. Lấy audio energy curve và chat volume curve trong 2 phút qua
2. Compute cross-correlation:
   correlation = cross_correlate(audio_energy, chat_volume, max_lag=15s)
3. optimal_lag = argmax(correlation)
4. Nếu abs(optimal_lag - current_lag) > 1s:
   → Update: current_lag = 0.7 * current_lag + 0.3 * optimal_lag
   → (Smoothed update, tránh jitter)
5. Log: lag_calibration_event { old_lag, new_lag, correlation_score }
```

#### Asymmetric Lag Model

```
Observation: Viewer reaction time phụ thuộc emotion type:

| Emotion | Typical Lag | Lý do |
|---|---|---|
| Funny | 2–3s | Laughter → instant reaction, gõ nhanh |
| Shock | 4–6s | Processing time: "wait what?" → then react |
| Drama | 5–8s | Need to understand context → form opinion → type |
| Emotional | 6–10s | Strong emotion → pause → then express |

Implementation:
  lag_by_category = {
    "funny": 2.5,
    "shock": 5.0,
    "drama": 6.5,
    "emotional": 8.0,
    "default": 5.0
  }
  
  // Khi correlate chat với event, dùng lag tương ứng category:
  adjusted_pts = chat_master_pts - lag_by_category[detected_emotion_type]
  
  // Vấn đề: chưa biết category trước khi correlate
  // Giải pháp: correlate với default lag trước, detect category,
  //            rồi re-correlate với category-specific lag
```

---

## PHẦN 5 — AI vs Non-AI Architecture

### 5A — Non-AI Components

| Component | Phương pháp | Lý do không cần AI |
|---|---|---|
| **Audio energy detection** | RMS computation (DSP) | Phép toán đơn giản, deterministic, 0 latency |
| **Audio pitch detection** | Autocorrelation / YIN algorithm (DSP) | Thuật toán classical, rất nhanh |
| **Silence detection** | RMS threshold (DSP) | Trivial threshold comparison |
| **Speaking rate** | Word count từ STT / duration | Arithmetic từ STT output |
| **Chat volume spike** | Count per window + z-score | Simple statistics |
| **Emoji pattern** | Regex + category mapping | Deterministic string matching |
| **Keyword detection** | Predefined keyword sets + string match | Dictionary lookup |
| **Gift/donation detection** | Event type check | Structured data from API |
| **Scene change** | Histogram difference (OpenCV) | Classical CV, CPU-friendly |
| **Motion detection** | Optical flow magnitude (OpenCV) | Classical CV |
| **Signal aggregation** | Weighted sum formula | Mathematical formula |
| **Event state machine** | Finite state machine | Deterministic transitions |
| **Timestamp alignment** | PTS arithmetic | Mathematical conversion |
| **Buffer management** | Ring buffer data structure | Standard data structure |
| **Cross-correlation** | scipy.signal.correlate | Classical signal processing |
| **Clip extraction** | FFmpeg segment copy | Container manipulation |

### 5B — AI Components

#### Small Local Models (CPU/GPU nhỏ)

| Component | Model | Tài nguyên | Tần suất gọi | Chi phí |
|---|---|---|---|---|
| **STT** | faster-whisper medium / PhoWhisper | 4 GB RAM, CPU | Continuous (mỗi 5s chunk) | Miễn phí (local) |
| **Laughter detection** | SVM/RF classifier trên spectral features | < 100 MB RAM, CPU | Continuous (mỗi 500ms) | Miễn phí (local) |
| **Simple sentiment** | VADER-like rules cho tiếng Việt hoặc tiny BERT | < 500 MB RAM, CPU | Per sentence từ STT | Miễn phí (local) |

#### Embedding Models (Phase 2)

| Component | Model | Tài nguyên | Tần suất | Chi phí |
|---|---|---|---|---|
| **Topic similarity** | multilingual-e5-small | 500 MB RAM, CPU | Per transcript segment (~mỗi 10s) | Miễn phí (local) |
| **Feedback clustering** | same embedding model | Same | Batch daily | Miễn phí |

#### LLM (qua OpenRouter)

| Component | Khi nào gọi | Model gợi ý | Tần suất | Chi phí ước lượng |
|---|---|---|---|---|
| **Boundary refinement** | Khi event CLOSED, cần xác nhận start/end | gemini-2.0-flash hoặc claude-3.5-haiku | < 5 lần/giờ/stream | ~$0.01–0.05/call |
| **Content classification** | Khi event scored > 0.8, cần classify type | Same | < 5 lần/giờ | ~$0.01/call |
| **Long event splitting** | Khi event > 3 phút, cần quyết định split points | Same | < 2 lần/giờ | ~$0.02/call |
| **Summary generation** | Khi clip exported, generate title/description | Same | Per clip | ~$0.01/call |

**Ước lượng LLM cost:**
- 1 stream × 4 giờ/session × ~10 LLM calls/giờ × $0.02/call = ~$0.80/session
- 3 streams × 20 sessions/tháng = ~$48/tháng
- **Vừa đủ budget $100/tháng** (còn dư cho storage, misc)

### 5C — LLM Gate Strategy

```
LLM Gate: Chỉ gọi LLM khi CẢ HAI điều kiện thỏa:

1. TRIGGER CONDITION (bắt buộc có ít nhất 1):
   a) Event CLOSED và score > 0.7 (worth refining boundary)
   b) Event duration > 180s (cần help split)
   c) 2+ events overlap (cần help resolve)
   d) Editor explicitly requests LLM analysis

2. RATE LIMIT:
   - Max 10 LLM calls per hour per stream
   - Min 30s gap giữa 2 calls
   - Daily budget cap: $5/day
   
3. LLM INPUT (structured prompt):
   {
     "task": "refine_highlight_boundary",
     "transcript": "<5 min transcript quanh event>",
     "signals": "<signal summary: peaks, energy curve, chat spikes>",
     "current_boundary": { "start": ..., "end": ... },
     "question": "Xác nhận start/end timestamp. 
                  Event bắt đầu khi nào? Kết thúc khi nào?"
   }

4. LLM OUTPUT (structured):
   {
     "refined_start_pts": ...,
     "refined_end_pts": ...,
     "content_type": "funny|drama|shock|...",
     "confidence": 0.0-1.0,
     "reasoning": "..."
   }

Những gì LLM làm mà non-LLM KHÔNG THỂ:
- Hiểu ngữ nghĩa phức tạp trong transcript (sarcasm, irony, setup-punchline)
- Xác định topic boundary chính xác khi topics blurred
- Generate human-readable summary/title cho clip
- Resolve ambiguous overlap khi cả 2 events cùng topic nhưng khác sub-topic
```

---

## PHẦN 6 — Event Candidate State Machine

### State Diagram

```
                    ┌───────────────────────┐
                    │                       │
        ┌──────────▶│       IDLE            │◀──────────────┐
        │           │  (no active event)    │               │
        │           └───────────┬───────────┘               │
        │                       │                           │
        │          composite_score > OPEN_THR               │
        │          (default 0.5)                            │
        │                       │                           │
        │                       ▼                           │
        │           ┌───────────────────────┐               │
        │           │                       │               │
   cancel           │      OPENING          │          cancel
   (false           │  (collecting signals, │          (timeout
   positive)        │   waiting for         │           exceeded)
        │           │   confirmation)       │               │
        │           └───┬───────────┬───────┘               │
        │               │           │                       │
        │    score > CONFIRM_THR    │                       │
        │    (0.65) within 8s  score < OPEN_THR             │
        │               │     for > 8s                      │
        │               │           │                       │
        │               ▼           └───────────────────────┘
        │   ┌───────────────────────┐
        │   │                       │
        │   │       ACTIVE          │
        │   │  (event confirmed,    │
        │   │   tracking peak,      │
        │   │   monitoring          │
        │   │   continuation)       │
        │   └───┬───────────┬───────┘
        │       │           │
        │   score < CLOSE_THR    score stays
        │   (0.25) for > 5s     > CLOSE_THR
        │       │           │
        │       │           └──── stay ACTIVE
        │       ▼                (extend event)
        │   ┌───────────────────────┐
        │   │                       │
        │   │       CLOSED          │
        │   │  (event finalized,    │
        └───│   ready for clip      │
            │   generation)         │
            └───────────────────────┘
                    │
                    ▼
            Generate Highlight
            Candidate → Clip
            Pipeline
```

### Transition Rules & Timeouts

| Transition | Condition | Timeout |
|---|---|---|
| **IDLE → OPENING** | `composite_score > OPEN_THR (0.5)` | — |
| **OPENING → ACTIVE** | `composite_score > CONFIRM_THR (0.65)` trong 8s kể từ OPENING | 8s: nếu không confirm → cancel |
| **OPENING → IDLE** (cancel) | Score giảm dưới OPEN_THR, hoặc timeout 8s | 8s |
| **ACTIVE → ACTIVE** (extend) | Score vẫn > CLOSE_THR (0.25) | — |
| **ACTIVE → CLOSED** | Score < CLOSE_THR (0.25) liên tục >= 5s, VÀ chat volume < 1.5x baseline | 5s cooldown |
| **ACTIVE → CLOSED** (forced) | Event duration > MAX_EVENT_DURATION (600s = 10 phút) | 600s hard limit |
| **CLOSED → generate clip** | Immediate sau CLOSED | — |

### Algorithm

```python
class EventCandidate:
    state: State = IDLE
    start_pts: float = 0
    peak_pts: float = 0
    peak_score: float = 0
    signals: List[SignalSnapshot] = []
    
    opening_time: float = 0      # khi chuyển sang OPENING
    below_close_since: float = 0 # khi score bắt đầu < CLOSE_THR

def process_snapshot(self, snapshot: SignalSnapshot):
    score = snapshot.composite_score
    
    if self.state == IDLE:
        if score > OPEN_THR:
            self.state = OPENING
            self.opening_time = snapshot.pts
            self.start_pts = snapshot.pts
            self.signals.append(snapshot)
    
    elif self.state == OPENING:
        self.signals.append(snapshot)
        
        if score > CONFIRM_THR:
            self.state = ACTIVE
            # Look back for actual start (trigger)
            self.start_pts = dynamic_context_expansion_backward(self.start_pts)
            
        elif snapshot.pts - self.opening_time > OPENING_TIMEOUT:
            self.state = IDLE  # cancel: false positive
            self.reset()
            
    elif self.state == ACTIVE:
        self.signals.append(snapshot)
        
        # Track peak
        if score > self.peak_score:
            self.peak_score = score
            self.peak_pts = snapshot.pts
        
        # Check close condition
        if score < CLOSE_THR:
            if self.below_close_since == 0:
                self.below_close_since = snapshot.pts
            elif snapshot.pts - self.below_close_since > CLOSE_COOLDOWN:
                self.state = CLOSED
                self.end_pts = self.below_close_since  # end at when it started dropping
        else:
            self.below_close_since = 0  # reset close timer
        
        # Hard timeout
        if snapshot.pts - self.start_pts > MAX_EVENT_DURATION:
            self.state = CLOSED
            self.end_pts = snapshot.pts
    
    elif self.state == CLOSED:
        # Trigger clip generation
        self.generate_highlight_candidate()
        self.state = IDLE
        self.reset()
```

---

## PHẦN 7 — Clip Generation

### 7A — Pre-roll / Post-roll

| Parameter | Default | Min | Max | Dynamic Expansion Condition |
|---|---|---|---|---|
| **Pre-roll** | 3s | 2s | 10s | Mở rộng nếu: trigger word nằm giữa câu (lùi về đầu câu); build-up rõ ràng trước trigger (lùi thêm 2–5s) |
| **Post-roll** | 2s | 1s | 5s | Mở rộng nếu: chat vẫn sôi nổi (laughter/emoji); streamer vẫn đang comment về event |
| **Context-aware trimming** | — | — | — | Thu hẹp nếu: silence > 2s ở đầu clip (cắt silence); event tiếp theo bắt đầu ngay (giảm post-roll) |

### 7B — User Adjustment Interface

#### Backend Architecture cho Adjustment

```
Thiết kế cho phép editor adjust mà KHÔNG cần re-process video:

1. SEGMENT-BASED STORAGE:
   Video đã được lưu dưới dạng 2s segments trong buffer/disk.
   Clip = ordered list of segment references + trim points.

2. CLIP DEFINITION (không phải file video):
   HighlightClip {
     clip_id: string
     stream_id: string
     event_id: string
     
     // Boundary (adjustable)
     start_pts: float        // editor có thể thay đổi
     end_pts: float          // editor có thể thay đổi
     
     // Segment references
     segments: [
       { path: "/segments/seg_150.ts", trim_start: 0.5, trim_end: null },
       { path: "/segments/seg_151.ts", trim_start: null, trim_end: null },
       ...
       { path: "/segments/seg_165.ts", trim_start: null, trim_end: 1.2 }
     ]
     
     // Metadata
     score: float
     content_type: string
     status: "DRAFT" | "FINAL" | "EXPORTED"
   }

3. KHI EDITOR ADJUST:
   - Thay đổi start_pts hoặc end_pts
   - Backend recalculate segment references (< 10ms)
   - NO video re-encoding needed
   - Preview: generate new concat list → FFmpeg stream copy → instant

4. KHI EXPORT:
   - FFmpeg concat demuxer: join segments → single .mp4
   - Stream copy (no re-encode): < 2s cho clip 1 phút
   - Hoặc re-encode nếu cần specific format/resolution
```

---

## PHẦN 8 — Realtime Export

### 8A — Draft vs Final Highlight

```
Highlight Lifecycle:

  Event ACTIVE + peak detected
        │
        ▼
  ┌──────────────────┐
  │  DRAFT HIGHLIGHT  │  ← Xuất ngay khi peak detected
  │                    │     start = estimated trigger
  │  - Pre-roll: full │     end = current (growing)
  │  - Post-roll: 0   │     Status: DRAFT
  │  - Score: current  │
  │  - Quality: partial│
  └────────┬───────────┘
           │
     Event CLOSED
           │
           ▼
  ┌──────────────────┐
  │  FINAL HIGHLIGHT  │  ← Upgrade khi event CLOSED
  │                    │     start = refined trigger
  │  - Pre-roll: full │     end = refined resolution
  │  - Post-roll: full│     Status: FINAL
  │  - Score: final    │
  │  - Quality: complete│
  └────────┬───────────┘
           │
     Editor reviews
           │
           ▼
  ┌──────────────────┐
  │  EXPORTED         │  ← Sau editor approve
  │  (.mp4 file ready)│     Status: EXPORTED
  └──────────────────┘

Notification flow:
  1. Draft created → push notification to editor UI:
     "🔥 New highlight detected at 20:15 — Score 0.85 (Funny)"
  2. Draft → Final upgrade → update UI:
     "✅ Highlight at 20:15 finalized — Duration 45s"
  3. Editor approves → export .mp4
```

### 8B — Avoiding Premature Export

```
Safeguards chống export quá sớm:

1. DRAFT có flag "is_growing = true":
   - UI hiển thị warning: "Event đang diễn ra, clip chưa hoàn chỉnh"
   - Editor KHÔNG thể export khi is_growing = true
   - Chỉ có thể "bookmark" để review sau

2. MINIMUM DURATION GATE:
   - Draft clip < 10s → không hiển thị (quá ngắn, likely noise)
   - Draft clip < 15s → hiển thị với warning "very short"

3. COOLDOWN BUFFER:
   - Sau peak, đợi ít nhất 10s trước khi cho phép export
   - Lý do: reaction/resolution cần thời gian

4. FORCED CLOSE PROTECTION:
   - Nếu event bị force-closed (timeout 10 phút):
     → Mark quality = "forced_close"
     → Alert editor: "Event rất dài, có thể cần split thủ công"
```

### 8C — Buffer Management cho Export

```
Export Pipeline cần video segments available:

1. KHI EVENT OPENED (OPENING state):
   → Pin video segments từ (trigger_pts - MAX_PRE_ROLL) đến hiện tại
   → Pinned segments sẽ KHÔNG bị circular buffer ghi đè

2. KHI EVENT ACTIVE:
   → Continue pinning new segments
   → Segments accumulate (event kéo dài = nhiều segments pinned)

3. KHI EVENT CLOSED:
   → Tất cả segments từ start_pts đến end_pts đều pinned
   → Copy pinned segments ra "staging area" (disk)
   → Release pin → circular buffer có thể reuse

4. KHI EXPORT:
   → FFmpeg đọc từ staging area → generate .mp4
   → Sau export thành công → xóa staging area (hoặc move to archive)

5. DISK PRESSURE:
   → Monitor disk usage
   → Nếu > 80% capacity:
     a) Expire old staging files (> 24h, chưa export)
     b) Alert editor: "Disk gần đầy, cần export hoặc delete highlights"
     c) Emergency: reduce buffer size tạm thời
```

---

## PHẦN 9 — AI Models Selection

### Model Comparison Table

| Component | Model khuyến nghị | Alternatives | GPU/CPU | RAM | VRAM | Chi phí | Self-host vs Cloud |
|---|---|---|---|---|---|---|---|
| **STT** | **faster-whisper medium** | PhoWhisper-medium, Whisper large-v3 | CPU (i7/Ryzen 7) | 4 GB | 0 | Miễn phí | ✅ Self-host |
| **Laughter detection** | **SVM trên MFCC features** | YAMNet (TF), CLAP | CPU | 200 MB | 0 | Miễn phí | ✅ Self-host |
| **Sentiment (VN)** | **PhoBERT-base** hoặc keyword rules | underthesea, VADER-VN | CPU | 500 MB | 0 | Miễn phí | ✅ Self-host |
| **Speaker diarization** | **pyannote.audio 3.0** (Phase 2) | Simple energy-based VAD | CPU (slow) / GPU | 2 GB | 2 GB | Miễn phí | ✅ Self-host (Phase 2) |
| **Source separation** | **Demucs v4** (Phase 2) | MDX-Net, bandpass filter | GPU needed | 4 GB | 4 GB | Miễn phí | ✅ Self-host (Phase 2) |
| **Embedding** | **multilingual-e5-small** (Phase 2) | paraphrase-multilingual-MiniLM | CPU | 500 MB | 0 | Miễn phí | ✅ Self-host |
| **LLM** | **gemini-2.0-flash** via OpenRouter | claude-3.5-haiku, gpt-4o-mini | Cloud API | N/A | N/A | ~$0.01–0.05/call | ☁️ Cloud API |

### Model Details

#### STT: faster-whisper medium

- **Vai trò:** Chuyển audio thành text tiếng Việt với word-level timestamps
- **Tại sao medium:** Balance accuracy/speed. Small quá kém cho tiếng Việt. Large quá chậm trên CPU.
- **Performance CPU:** ~3s inference cho 5s audio trên i7-12700 (vừa đủ realtime)
- **WER tiếng Việt:** ~15–25% (medium), ~10–15% (large-v3)
- **RAM:** ~4 GB (CTranslate2 format, quantized INT8)
- **Ưu:** Miễn phí, local, word timestamps, VAD tích hợp
- **Nhược:** Accuracy tiếng Việt trung bình, cần fine-tune cho slang/informal speech
- **Alternative:** PhoWhisper (VinAI fine-tune trên tiếng Việt) — accuracy tốt hơn, nhưng cần check nếu có CTranslate2 format

#### LLM: gemini-2.0-flash via OpenRouter

- **Vai trò:** Boundary refinement, content classification, summary generation
- **Tại sao flash:** Rẻ nhất trong các model đủ capable. ~$0.075/1M input tokens, ~$0.30/1M output tokens.
- **Typical call:** ~2000 input tokens (transcript + signals) + ~200 output tokens = ~$0.0002/call
- **Ưu:** Rất rẻ, nhanh (~1–2s response), hiểu tiếng Việt tốt
- **Nhược:** Không bằng GPT-4o/Claude cho reasoning phức tạp
- **Khi cần reasoning tốt hơn:** Upgrade sang claude-3.5-haiku hoặc gpt-4o-mini (~$0.001/call)

---

## PHẦN 10 — Scalability Design

### Resource Estimates

| Resource | 1–3 Streams (MVP) | 10 Streams | 100 Streams | 1000 Streams |
|---|---|---|---|---|
| **CPU** | 4–8 cores (1 máy i7) | 16–32 cores (1 server) | 8–16 servers (16 cores mỗi) | 80–160 servers |
| **RAM** | 16 GB | 64 GB | 64 GB × 10 servers | 64 GB × 100 servers |
| **GPU** | Không cần | 1× RTX 3060 (optional) | 4–8 × RTX 3060/4060 | 40–80 GPUs |
| **Storage (live buffer)** | 1 GB | 3 GB | 30 GB | 300 GB |
| **Storage (clips/day)** | 5 GB | 50 GB | 500 GB | 5 TB |
| **Network bandwidth** | 15 Mbps | 50 Mbps | 500 Mbps | 5 Gbps |
| **Message Queue** | Redis (single node) | Redis (single node) | Redis Cluster / Kafka | Kafka cluster (3+ brokers) |
| **Database** | SQLite | PostgreSQL (single) | PostgreSQL (primary + replica) | PostgreSQL (sharded) + TimescaleDB |

### Message Queue Design

#### MVP (1–3 streams): Redis Streams

```
Streams:
  stream:{stream_id}:audio_chunks    ← Audio chunks cho STT
  stream:{stream_id}:signals         ← Processed signals
  stream:{stream_id}:events          ← Event state changes
  stream:{stream_id}:highlights      ← Highlight candidates
  
Consumer groups:
  stt-workers       ← consumes audio_chunks
  signal-aggregator ← consumes signals
  event-detector    ← consumes aggregated signals
  clip-generator    ← consumes highlights
```

#### Scale (100+ streams): Kafka

```
Topics:
  livestream.audio.chunks     (partitioned by stream_id)
  livestream.signals.raw      (partitioned by stream_id)
  livestream.signals.aligned  (partitioned by stream_id)
  livestream.events           (partitioned by stream_id)
  livestream.highlights       (partitioned by stream_id)
  
Partition count: number_of_streams (1 partition per stream)
Replication factor: 3 (production)
Retention: 24 hours
```

### Database Schema (Core Tables)

```sql
-- Stream registry
CREATE TABLE streams (
  stream_id       TEXT PRIMARY KEY,
  platform        TEXT NOT NULL,      -- 'tiktok', 'youtube', 'facebook'
  url             TEXT NOT NULL,
  streamer_name   TEXT,
  content_type    TEXT,               -- 'talkshow', 'gaming', 'entertainment'
  status          TEXT DEFAULT 'IDLE', -- 'IDLE', 'RECORDING', 'ENDED', 'ERROR'
  started_at      DATETIME,
  ended_at        DATETIME,
  config          TEXT,               -- JSON: custom thresholds, weights
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Event candidates
CREATE TABLE events (
  event_id        TEXT PRIMARY KEY,
  stream_id       TEXT NOT NULL REFERENCES streams(stream_id),
  state           TEXT NOT NULL,       -- 'OPENING', 'ACTIVE', 'CLOSED', 'CANCELLED'
  start_pts       REAL,
  end_pts         REAL,
  peak_pts        REAL,
  peak_score      REAL,
  duration_sec    REAL,
  content_type    TEXT,
  
  -- Scores
  drama_score     REAL,
  shock_score     REAL,
  emotion_score   REAL,
  curiosity_score REAL,
  retention_score REAL,
  virality_score  REAL,
  composite_score REAL,
  
  -- Quality
  context_status  TEXT DEFAULT 'COMPLETE', -- 'COMPLETE', 'PARTIAL', 'BUFFER_LIMITED'
  
  -- LLM refinement
  llm_refined     BOOLEAN DEFAULT FALSE,
  llm_response    TEXT,                    -- JSON
  
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Highlight clips
CREATE TABLE highlights (
  highlight_id    TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL REFERENCES events(event_id),
  stream_id       TEXT NOT NULL REFERENCES streams(stream_id),
  
  start_pts       REAL NOT NULL,
  end_pts         REAL NOT NULL,
  duration_sec    REAL NOT NULL,
  
  pre_roll_sec    REAL DEFAULT 3.0,
  post_roll_sec   REAL DEFAULT 2.0,
  
  status          TEXT DEFAULT 'DRAFT',  -- 'DRAFT', 'FINAL', 'REVIEWED', 'EXPORTED'
  score           REAL,
  
  -- Platform-specific versions
  platform_target TEXT,                  -- 'tiktok', 'youtube_shorts', 'reels', 'youtube_clip'
  
  -- File paths
  staging_path    TEXT,                  -- path to staged segments
  export_path     TEXT,                  -- path to exported .mp4
  
  -- Editor
  reviewed_by     TEXT,
  reviewed_at     DATETIME,
  
  title           TEXT,
  description     TEXT,
  
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Signal events (time-series, high volume)
-- For MVP: SQLite is fine
-- For scale: migrate to TimescaleDB
CREATE TABLE signal_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_id       TEXT NOT NULL,
  signal_type     TEXT NOT NULL,
  master_pts      REAL NOT NULL,
  value           REAL NOT NULL,
  confidence      REAL DEFAULT 1.0,
  drift_ms        REAL DEFAULT 0,
  source          TEXT NOT NULL,
  metadata        TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_signals_stream_pts ON signal_events(stream_id, master_pts);
CREATE INDEX idx_signals_type ON signal_events(signal_type, master_pts);

-- Feedback (Section 3I schema already defined above)
```

### Worker Architecture

#### MVP: Single Process

```
1 Python process per stream:
  - 1 thread: StreamRecorder (yt-dlp + FFmpeg)
  - 1 thread: ChatCollector (WebSocket)
  - 1 thread: STT Worker (faster-whisper)
  - 1 thread: Signal Pipeline (DSP + aggregation + event detection)
  - Main thread: Coordinator + API server (FastAPI)

Tổng: 1 process × 4–5 threads × 3 streams = ~15 threads trên 1 máy
CPU: i7/Ryzen 7 (8 cores) → đủ cho 3 streams
```

#### Scale (10+ streams): Worker Pool

```
┌─────────────────────────────────────────┐
│           Orchestrator Service          │
│  (FastAPI, manages stream lifecycle)    │
└────────────────┬────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│ Worker 1│ │ Worker 2│ │ Worker N│
│ (3-5    │ │ (3-5    │ │ (3-5    │
│ streams)│ │ streams)│ │ streams)│
└─────────┘ └─────────┘ └─────────┘

Auto-scaling trigger:
  - CPU usage > 70% sustained 5 min → add worker
  - CPU usage < 30% sustained 10 min → remove worker
  - STT latency > 5s → add worker (STT overloaded)
```

---

## PHẦN 11 — Cost Optimization

### Chiến lược giảm chi phí

| Chiến lược | Impact | Effort | Priority |
|---|---|---|---|
| **Local STT (Whisper)** | Saves $50–200/tháng vs cloud STT | Low (already planned) | ✅ MVP |
| **LLM Gate (call only when needed)** | Saves $200–500/tháng vs continuous LLM | Medium | ✅ MVP |
| **Whisper INT8 quantization** | 2x speed, same quality | Low (CTranslate2 builtin) | ✅ MVP |
| **Skip video analysis MVP** | Saves GPU cost entirely | Low (defer) | ✅ MVP |
| **Selective audio processing** | Process only when energy > minimum | Low | Phase 2 |
| **Batch LLM calls** | Group 2-3 events per call → fewer calls | Medium | Phase 2 |
| **Spot/preemptible instances** | 60–80% savings on GPU instances | Medium (need retry logic) | Phase 3 |
| **Model distillation** | Train smaller model from LLM feedback | High | Phase 4 |

### Monthly Cost Estimates

| Component | 1–3 Streams | 10 Streams | 100 Streams | 1000 Streams |
|---|---|---|---|---|
| **Compute (CPU server)** | $0 (local PC) | $50–100 (cloud VM) | $500–1000 | $5,000–10,000 |
| **GPU** | $0 | $0–50 (optional) | $200–800 | $2,000–8,000 |
| **STT (local Whisper)** | $0 | $0 | $0 (included in compute) | $0 |
| **LLM (OpenRouter)** | $20–50 | $50–150 | $500–1,500 | $5,000–15,000 |
| **Storage** | $0 (local disk) | $10–20 (S3/R2) | $50–200 | $500–2,000 |
| **Network** | $0 (home internet) | $10–20 | $50–200 | $500–1,000 |
| **Message Queue** | $0 (local Redis) | $0–20 | $50–200 (Kafka) | $200–500 |
| **Database** | $0 (SQLite) | $0–20 (PostgreSQL) | $50–200 | $200–500 |
| **Monitoring** | $0 | $0–20 | $50–100 | $100–300 |
| **TỔNG** | **$20–50** | **$120–400** | **$1,450–4,200** | **$13,500–37,300** |

> **Note:** Estimates dựa trên cloud pricing (AWS/GCP). Self-host giảm 40–60%.

---

## PHẦN 12 — MVP Roadmap

### Phase 1 — MVP (8–10 tuần)

**Mục tiêu:** End-to-end system hoạt động với 1 TikTok Live stream.

| Task | Độ khó | Thời gian | Milestone |
|---|---|---|---|
| Stream ingestion (yt-dlp + FFmpeg) | 2/5 | 1 tuần | Có thể record TikTok live stream liên tục |
| Chat collection (TikTok-Live-Connector) | 3/5 | 1 tuần | Nhận được chat messages realtime |
| Circular buffer (video + audio + transcript + chat) | 3/5 | 1.5 tuần | Buffer hoạt động, có thể look-back |
| STT pipeline (faster-whisper) | 2/5 | 1 tuần | Transcript tiếng Việt realtime |
| Audio DSP (energy, pitch, silence, laughter) | 3/5 | 1.5 tuần | Tất cả audio signals hoạt động |
| Chat analyzer (volume, emoji, keyword) | 2/5 | 0.5 tuần | Chat signals hoạt động |
| Signal aggregator + timestamp alignment | 3/5 | 1 tuần | Signals aligned, composite score |
| Event state machine + highlight scoring | 4/5 | 1.5 tuần | Events detected, scored |
| Clip generation (FFmpeg extract) | 2/5 | 0.5 tuần | Clips exported as .mp4 |
| Basic editor UI (FastAPI + HTMX) | 3/5 | 1 tuần | Editor có thể review/approve highlights |

**Milestone Phase 1:** Editor nhìn thấy highlight candidates tự động, review, adjust boundaries, export clip.

### Phase 2 — Beta (6–8 tuần)

**Mục tiêu:** Improve accuracy, thêm feedback loop, support multiple content types.

| Task | Độ khó | Thời gian |
|---|---|---|
| Dynamic Context Expansion (look-back/forward) | 4/5 | 2 tuần |
| Overlapping event resolution | 3/5 | 1 tuần |
| Long event splitting | 3/5 | 1 tuần |
| Cold start handling (3-tier baseline) | 3/5 | 1 tuần |
| Chat lag compensation | 3/5 | 1 tuần |
| LLM gate (boundary refinement) | 3/5 | 1 tuần |
| Feedback loop (editor corrections → learning) | 4/5 | 1.5 tuần |
| Multi-stream support (3 concurrent) | 2/5 | 0.5 tuần |

**Milestone Phase 2:** System detect highlights với accuracy đủ tốt để editor sử dụng hàng ngày. Feedback loop bắt đầu improve quality.

### Phase 3 — Production (6–8 tuần)

**Mục tiêu:** Reliability, monitoring, scale lên 10+ streams.

| Task | Độ khó | Thời gian |
|---|---|---|
| YouTube Live support | 3/5 | 1.5 tuần |
| Facebook Live support | 3/5 | 1.5 tuần |
| Worker pool architecture | 4/5 | 2 tuần |
| Monitoring & alerting (Prometheus/Grafana) | 3/5 | 1 tuần |
| Video analysis (scene change, motion) | 3/5 | 1 tuần |
| Cost optimization (batching, caching) | 2/5 | 1 tuần |
| Backup & disaster recovery | 2/5 | 0.5 tuần |

**Milestone Phase 3:** System chạy ổn định 10+ streams, có monitoring, multi-platform.

### Phase 4 — Advanced AI (8–12 tuần)

**Mục tiêu:** Advanced features, adaptive learning, scale.

| Task | Độ khó | Thời gian |
|---|---|---|
| Source separation (Demucs) | 4/5 | 2 tuần |
| Speaker diarization | 4/5 | 2 tuần |
| Embedding-based topic detection | 3/5 | 1.5 tuần |
| A/B testing framework | 3/5 | 1 tuần |
| Virality prediction model | 5/5 | 3 tuần |
| Auto weight learning (regression) | 3/5 | 1 tuần |
| Platform-specific clip formatting | 2/5 | 1 tuần |
| Scale to 100+ streams | 5/5 | 3 tuần |

**Milestone Phase 4:** System tự học từ feedback, predict viral potential, scale lên 100+ streams.

---

## PHẦN 13 — Risk Register

### Technical Risks

| Risk | Severity | Probability | Phòng ngừa | Contingency |
|---|---|---|---|---|
| **STT accuracy thấp cho tiếng Việt** | High | Medium | Test PhoWhisper, fine-tune trên domain data | Fallback: dùng audio-only signals (energy, laughter), giảm weight transcript signals |
| **HLS latency quá cao** | Medium | Low | Đo latency trước khi commit. Backup: FLV/WebSocket | Accept 15s delay, hoặc switch sang TikTok-Live-Connector |
| **Timestamp drift giữa sources** | High | Medium | Drift detection mỗi 60s, auto re-sync | Manual alignment tool cho editor. Log all drifts. |
| **Buffer overflow (event quá dài)** | Medium | Low | Pin mechanism + disk overflow | Hard timeout 10 phút + alert editor |
| **Cold start miss highlight** | High | High | 3-tier baseline, lower threshold Phase 0 | Accept higher false positive ở 5 phút đầu |
| **Laughter detection false positive** | Medium | Medium | SVM trained trên good dataset, per-stream calibration | Fallback: weight laughter signal thấp hơn |
| **FFmpeg pipeline crash** | Medium | Medium | Auto-restart với exponential backoff | Buffer flush trước restart, gap marker |
| **Model accuracy degradation over time** | Medium | Low | Weekly metric monitoring, A/B test | Rollback to previous model, alert |

### Product Risks

| Risk | Severity | Probability | Phòng ngừa | Contingency |
|---|---|---|---|---|
| **Highlight quality chưa đủ production** | High | Medium | Ưu tiên recall > precision, editor review layer | Manual highlight marking tool song song AI |
| **Editor reject rate > 50%** | High | Medium | Feedback loop, per-content-type tuning | Lower sensitivity (fewer but better highlights), focus on high-confidence only |
| **Clip thiếu context (cắt mất setup)** | High | Medium | Dynamic Context Expansion, generous pre-roll | Default pre-roll 5s thay vì 3s, LLM boundary check |
| **Quá nhiều false positive gây overload editor** | Medium | Medium | Raise OPEN_THRESHOLD, rate limit highlights/hour | Max 5 highlights/hour/stream cap |

### Data Risks

| Risk | Severity | Probability | Phòng ngừa | Contingency |
|---|---|---|---|---|
| **TikTok block scraping** | High | High | Rotate IP, user-agent. Backup: TikTok-Live-Connector | Switch platform (YouTube first), develop official API relationship |
| **TikTok đổi API/protocol** | High | High | Monitor TikTok-Live-Connector repo cho updates | Fork and maintain, community patches |
| **GDPR/Copyright khi lưu livestream** | Medium | Low (internal tool) | Chỉ lưu buffer 10 phút, auto-delete. Clip lưu chỉ khi editor approve. | Add data retention policy, auto-expire sau 30 ngày |
| **Chat data quality (spam, bot)** | Medium | High | Spam filter, dedup, per-user rate limit | Weight chat signals thấp hơn nếu quality kém |

### Cost Risks

| Risk | Severity | Probability | Phòng ngừa | Contingency |
|---|---|---|---|---|
| **LLM cost vượt budget** | Medium | Medium | LLM Gate strict, rate limit, budget cap/day | Disable LLM entirely, rely only on rule-based | 
| **GPU cost khi scale** | High | Medium (Phase 3+) | Spot instances, quantization, selective processing | Defer GPU-heavy features (source separation, video analysis) |
| **Storage cost accumulation** | Low | Low | Auto-delete buffers, retention policy | Compress clips, lower resolution storage |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **PTS** | Presentation Timestamp — thời điểm frame/sample được hiển thị |
| **DTS** | Decoding Timestamp — thời điểm frame cần được decode |
| **HLS** | HTTP Live Streaming — protocol streaming bằng HTTP segments |
| **FLV** | Flash Video — container format thường dùng trong RTMP/live |
| **STT** | Speech-to-Text — chuyển đổi giọng nói thành văn bản |
| **DSP** | Digital Signal Processing — xử lý tín hiệu số |
| **VAD** | Voice Activity Detection — phát hiện khi có người nói |
| **RMS** | Root Mean Square — metric đo energy âm thanh |
| **MFCC** | Mel-Frequency Cepstral Coefficients — features cho audio classification |
| **WER** | Word Error Rate — tỷ lệ lỗi từ trong STT |

## Appendix B — Config Defaults

```yaml
# Thresholds (calibrated, can be overridden per stream)
thresholds:
  open_threshold: 0.50        # Score to open event candidate
  confirm_threshold: 0.65     # Score to confirm event (OPENING → ACTIVE)
  close_threshold: 0.25       # Score below which event closes
  peak_threshold: 0.75        # Score to mark peak
  opening_timeout_sec: 8      # Max time in OPENING before cancel
  close_cooldown_sec: 5       # Time below close_threshold before CLOSED
  max_event_duration_sec: 600 # Hard limit on single event

# Buffer sizes
buffers:
  video_duration_sec: 600     # 10 minutes
  audio_duration_sec: 600     # 10 minutes
  transcript_duration_sec: 900 # 15 minutes
  chat_duration_sec: 900      # 15 minutes

# Pre-roll / Post-roll
clip:
  pre_roll_default_sec: 3.0
  pre_roll_min_sec: 2.0
  pre_roll_max_sec: 10.0
  post_roll_default_sec: 2.0
  post_roll_min_sec: 1.0
  post_roll_max_sec: 5.0

# STT
stt:
  model: "medium"             # whisper model size
  chunk_duration_sec: 5       # audio chunk for STT
  chunk_overlap_sec: 0.5      # overlap between chunks
  language: "vi"
  compute_type: "int8"        # quantization

# LLM Gate
llm:
  provider: "openrouter"
  model: "google/gemini-2.0-flash-001"
  max_calls_per_hour: 10
  min_gap_between_calls_sec: 30
  daily_budget_usd: 5.0
  enabled: true

# Chat lag
chat:
  default_lag_sec: 5.0
  lag_calibration_interval_sec: 900  # 15 minutes
  lag_by_category:
    funny: 2.5
    shock: 5.0
    drama: 6.5
    emotional: 8.0
    default: 5.0

# Cold start
cold_start:
  phase0_end_sec: 60
  phase1_end_sec: 300
  threshold_reduction_phase0: 0.80   # multiply thresholds by this
  threshold_reduction_phase1: 0.90

# Scoring weights (default, overridden per content type)
scoring:
  drama: 0.20
  shock: 0.20
  emotion: 0.15
  curiosity: 0.15
  retention: 0.15
  virality: 0.15
```
