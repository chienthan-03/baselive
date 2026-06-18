import numpy as np
from typing import List, Dict

from src.pipeline.audio_dsp import AudioAnalyzer
from src.pipeline.chat_analyzer import ChatAnalyzer
from src.pipeline.stt_analyzer import STTAnalyzer
from src.engine.aggregator import SignalAggregator
from src.engine.clip_generator import ClipGenerator
from src.core.models import SignalSnapshot, TranscriptResult
from src.engine.state_machine import StateMachine
from src.db.database import Database


class MasterPipeline:
    def __init__(
        self,
        clip_source: str = "",
        output_dir: str = "output/clips",
        db: Database = None,
        stream_id: str = "default",
        stt_enabled: bool = True,
    ):
        self.audio_analyzer = AudioAnalyzer()
        self.chat_analyzer = ChatAnalyzer()
        self.stt_analyzer = STTAnalyzer()
        self.aggregator = SignalAggregator(stt_enabled=stt_enabled)
        self.state_machine = StateMachine()
        self.output_dir = output_dir
        self.clip_generator = ClipGenerator(clip_source, output_dir) if clip_source else None
        self.db = db
        self.stream_id = stream_id

    def process_chunk(
        self,
        pts: float,
        audio_data: np.ndarray,
        chat_messages: List[Dict],
        transcript: List[Dict] = None,
        clip_source: str = "",
    ) -> None:
        if clip_source:
            if self.clip_generator is None:
                self.clip_generator = ClipGenerator(clip_source, self.output_dir)
            else:
                self.clip_generator.source_file = clip_source

        prev_state = self.state_machine.current_event.state

        audio_res = self.audio_analyzer.analyze_chunk(audio_data)
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
        )

        self.aggregator.compute_score(snapshot)

        baseline = max(self.chat_analyzer.baseline_volume, 1e-6)
        chat_volume_ratio = chat_res["raw_volume"] / baseline
        self.state_machine.process(snapshot, chat_volume_ratio=chat_volume_ratio)

        if prev_state == "ACTIVE" and self.state_machine.current_event.state == "CLOSED":
            clip_path = ""
            if self.clip_generator:
                clip_path = self.clip_generator.generate(self.state_machine.current_event)

            if self.db:
                ev = self.state_machine.current_event
                self.db.insert_highlight(
                    stream_id=self.stream_id,
                    start_pts=ev.start_pts,
                    end_pts=ev.end_pts,
                    score=ev.peak_score,
                    clip_path=clip_path,
                    status="PENDING",
                    reason="Pipeline detected highlight",
                )
