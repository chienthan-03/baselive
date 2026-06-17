import pytest
import numpy as np
from src.engine.pipeline import MasterPipeline

def test_pipeline_integration():
    pipeline = MasterPipeline()
    # Mock data to simulate a spike
    audio_chunk = np.random.normal(0, 0.8, 16000 * 5) # loud audio
    chat_msgs = [{"msg": "haha", "pts": 1.0}] * 10    # chat spike
    
    pipeline.process_chunk(pts=10.0, audio_data=audio_chunk, chat_messages=chat_msgs)
    
    # Due to loud audio and high chat volume, an event should open
    assert pipeline.state_machine.current_event.state in ["OPENING", "ACTIVE"]
