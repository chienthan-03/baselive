import numpy as np
from typing import List, Dict, Optional

from src.pipeline.audio_dsp import AudioAnalyzer
from src.pipeline.chat_analyzer import ChatAnalyzer
from src.pipeline.stt_analyzer import STTAnalyzer
from src.engine.aggregator import SignalAggregator
from src.engine.clip_generator import ClipGenerator
from src.core.models import SignalSnapshot, TranscriptResult, ClosedEventInfo
from src.engine.state_machine import StateMachine
from src.engine.baseline_calibrator import BaselineCalibrator, RollingStats
from src.buffer.circular_buffer import TranscriptBuffer
from src.buffer.signal_history import SignalHistoryBuffer
from src.db.database import Database

NOISE_FLOOR = 0.02


class MasterPipeline:
    def __init__(
        self,
        clip_source: str = "",
        output_dir: str = "output/clips",
        db: Database = None,
        stream_id: str = "default",
        stt_enabled: bool = True,
        highlight_processor=None,
        transcript_buffer: TranscriptBuffer = None,
    ):
        self.audio_analyzer = AudioAnalyzer()
        self.chat_analyzer = ChatAnalyzer()
        self.stt_analyzer = STTAnalyzer()
        self.aggregator = SignalAggregator(stt_enabled=stt_enabled)
        self.state_machine = StateMachine()
        self.calibrator = BaselineCalibrator()
        self.rolling_stats = RollingStats()
        self.rolling_stats_1min = RollingStats(window_sec=60)
        self.stream_start_pts: Optional[float] = None
        self._last_recalibrate_pts: Optional[float] = None
        self.signal_history = SignalHistoryBuffer()
        self.output_dir = output_dir
        self.clip_generator = ClipGenerator(clip_source, output_dir) if clip_source else None
        self.db = db
        self.stream_id = stream_id
        self.highlight_processor = highlight_processor
        self.transcript_buffer = transcript_buffer
        self._quiet_streak = 0

    def process_chunk(
        self,
        pts: float,
        audio_data: np.ndarray,
        chat_messages: List[Dict],
        transcript: List[Dict] = None,
        clip_source: str = "",
        video_signals: Optional[Dict] = None,
    ) -> Optional[ClosedEventInfo]:
        if clip_source:
            if self.clip_generator is None:
                self.clip_generator = ClipGenerator(clip_source, self.output_dir)
            else:
                self.clip_generator.source_file = clip_source

        prev_state = self.state_machine.current_event.state

        raw_rms = self.audio_analyzer._compute_rms(audio_data)
        if raw_rms < NOISE_FLOOR:
            self._quiet_streak += 1
        else:
            self._quiet_streak = 0

        audio_res = self.audio_analyzer.analyze_chunk(
            audio_data,
            run_full_dsp=self._quiet_streak < 5,
        )
        chat_res = self.chat_analyzer.analyze_batch(chat_messages)

        stt_res = None
        transcript_text = ""
        if transcript:
            latest = transcript[-1]
            item = latest.get("item")
            if isinstance(item, TranscriptResult):
                duration_sec = len(audio_data) / self.audio_analyzer.sample_rate
                stt_res = self.stt_analyzer.analyze(item, duration_sec)
                transcript_text = item.text

        keywords = list(chat_res.get("keyword_triggered", []))
        speaking_rate = 0.0
        sentiment_shift = 0.0
        sentence_rate = 0.0
        if stt_res:
            speaking_rate = stt_res["speaking_rate"]
            sentiment_shift = stt_res["sentiment_shift"]
            sentence_rate = stt_res["sentence_rate"]
            for kw in stt_res.get("keyword_triggered", []):
                if kw not in keywords:
                    keywords.append(kw)

        video_scene_change = 0.0
        video_motion = 0.0
        if video_signals:
            video_scene_change = float(video_signals.get("video_scene_change", 0.0))
            video_motion = float(video_signals.get("video_motion", 0.0))

        snapshot = SignalSnapshot(
            pts=pts,
            audio_energy=audio_res["energy_score"],
            audio_energy_spike=audio_res["energy_spike"],
            silence_before=audio_res["silence_before"],
            pitch_deviation=audio_res["pitch_deviation"],
            speaking_rate=speaking_rate,
            speaker_overlap=audio_res["speaker_overlap"],
            laughter_prob=audio_res["laughter_prob"],
            transcript_text=transcript_text,
            sentiment_shift=sentiment_shift,
            keyword_triggered=keywords,
            sentence_rate=sentence_rate,
            chat_volume_spike=chat_res["chat_volume_spike"],
            chat_emoji_scores=chat_res["chat_emoji_scores"],
            chat_keyword_cluster=chat_res.get("chat_keyword_cluster"),
            gift_event=chat_res.get("gift_event"),
            video_scene_change=video_scene_change,
            video_motion=video_motion,
        )

        self.aggregator.compute_score(snapshot)
        self.signal_history.append(snapshot)

        if self.stream_start_pts is None:
            self.stream_start_pts = pts

        self.rolling_stats.append(pts, snapshot.composite_score)
        self.rolling_stats_1min.append(pts, snapshot.composite_score)

        if self.calibrator.detect_activity_change(
            self.rolling_stats_1min, self.rolling_stats
        ):
            self.rolling_stats = RollingStats()
            self.rolling_stats_1min = RollingStats(window_sec=60)
            self.rolling_stats.append(pts, snapshot.composite_score)
            self.rolling_stats_1min.append(pts, snapshot.composite_score)

        elapsed_sec = pts - self.stream_start_pts
        thresholds = self.calibrator.get_thresholds(elapsed_sec, self.rolling_stats)

        if elapsed_sec >= 300:
            if (
                self._last_recalibrate_pts is None
                or pts - self._last_recalibrate_pts >= 30
            ):
                self.calibrator.recalibrate()
                self._last_recalibrate_pts = pts

        baseline = max(self.chat_analyzer.baseline_volume, 1e-6)
        chat_volume_ratio = chat_res["raw_volume"] / baseline
        self.state_machine.process(
            snapshot,
            chat_volume_ratio=chat_volume_ratio,
            thresholds=thresholds,
        )

        ev = self.state_machine.current_event
        new_state = ev.state

        if prev_state == "OPENING" and new_state == "ACTIVE":
            ev.is_growing = True
            if self.db:
                highlight_id = self.db.insert_highlight(
                    stream_id=self.stream_id,
                    start_pts=ev.start_pts,
                    end_pts=pts,
                    score=ev.peak_score,
                    status="PENDING",
                    reason="Pipeline detected highlight",
                    highlight_type="DRAFT",
                    is_growing=1,
                    quality="partial",
                    peak_pts=ev.peak_pts,
                )
                ev.draft_highlight_id = highlight_id
                if self.highlight_processor is not None:
                    self.highlight_processor.record_highlight_created("DRAFT")
        elif new_state == "ACTIVE" and ev.draft_highlight_id is not None and self.db:
            self.db.update_highlight(
                ev.draft_highlight_id,
                score=ev.peak_score,
                peak_pts=ev.peak_pts,
                end_pts=pts,
            )

        if (
            self.highlight_processor is not None
            and self.highlight_processor.pending_queue.is_ready(pts)
            and self.transcript_buffer is not None
        ):
            self.highlight_processor.process_pending_queue(
                self.signal_history,
                self.transcript_buffer,
                clip_source,
            )

        closed_info = None
        if prev_state == "ACTIVE" and new_state == "CLOSED":
            if self.db and ev.draft_highlight_id is not None:
                self.db.update_highlight(
                    ev.draft_highlight_id,
                    is_growing=0,
                    end_pts=ev.end_pts,
                    score=ev.peak_score,
                    peak_pts=ev.peak_pts,
                )
            closed_info = ClosedEventInfo(event=ev, close_pts=ev.end_pts)

        return closed_info
