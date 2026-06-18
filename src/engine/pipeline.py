import numpy as np
from typing import List, Dict

from src.pipeline.audio_dsp import AudioAnalyzer
from src.pipeline.chat_analyzer import ChatAnalyzer
from src.engine.aggregator import SignalAggregator
from src.engine.clip_generator import ClipGenerator
from src.core.models import SignalSnapshot
from src.core.models import EventCandidate
from src.db.database import Database

# We need to import StateMachine, but it was not created in Phase 1.1 or 1.2!
# Let me mock a simple StateMachine for now since it was part of Phase 1 MVP but I might have missed its implementation.
# Wait, let me check if I created state_machine.py

class StateMachine:
    OPEN_THR = 0.5
    CONFIRM_THR = 0.65
    CLOSE_THR = 0.25
    CLOSE_COOLDOWN = 5.0
    
    def __init__(self):
        self.current_event = EventCandidate()
        
    def process(self, snapshot: SignalSnapshot):
        score = snapshot.composite_score
        pts = snapshot.pts
        ev = self.current_event
        
        if ev.state == "IDLE":
            if score > self.OPEN_THR:
                ev.state = "OPENING"
                ev.start_pts = pts
                
        elif ev.state == "OPENING":
            if score > self.CONFIRM_THR:
                ev.state = "ACTIVE"
                ev.peak_score = score
                ev.peak_pts = pts
            elif pts - ev.start_pts > 8.0:
                ev.state = "IDLE" # Cancel
                
        elif ev.state == "ACTIVE":
            if score > ev.peak_score:
                ev.peak_score = score
                ev.peak_pts = pts
                
            if score < self.CLOSE_THR:
                if ev.below_close_since == 0.0:
                    ev.below_close_since = pts
                elif pts - ev.below_close_since >= self.CLOSE_COOLDOWN:
                    ev.state = "CLOSED"
                    ev.end_pts = ev.below_close_since
            else:
                ev.below_close_since = 0.0


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
