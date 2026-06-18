import numpy as np
from typing import List, Dict

from src.pipeline.audio_dsp import AudioAnalyzer
from src.pipeline.chat_analyzer import ChatAnalyzer
from src.engine.aggregator import SignalAggregator
from src.engine.clip_generator import ClipGenerator
from src.core.models import SignalSnapshot
from src.engine.state_machine import StateMachine
from src.db.database import Database


class MasterPipeline:
    def __init__(self, clip_source: str = "", output_dir: str = "output/clips", 
                 db: Database = None, stream_id: str = "default"):
        self.audio_analyzer = AudioAnalyzer()
        self.chat_analyzer = ChatAnalyzer()
        self.aggregator = SignalAggregator()
        self.state_machine = StateMachine()
        self.clip_generator = ClipGenerator(clip_source, output_dir) if clip_source else None
        self.db = db
        self.stream_id = stream_id
        
    def process_chunk(self, pts: float, audio_data: np.ndarray, chat_messages: List[Dict]):
        # Capture state before processing
        prev_state = self.state_machine.current_event.state

        # Analyze audio
        audio_res = self.audio_analyzer.analyze_chunk(audio_data)
        
        # Analyze chat
        chat_res = self.chat_analyzer.analyze_batch(chat_messages)
        
        # Construct snapshot
        snapshot = SignalSnapshot(
            pts=pts,
            audio_energy_spike=audio_res["energy_spike"],
            chat_volume_spike=chat_res["chat_volume_spike"]
        )
        
        # Compute composite score
        self.aggregator.compute_score(snapshot)
        
        # Drive state machine
        self.state_machine.process(snapshot)

        # Emit clip whenever an event just closed
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
                    reason="Pipeline detected highlight"
                )
