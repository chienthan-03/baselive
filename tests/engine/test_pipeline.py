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

from unittest.mock import patch, MagicMock

def test_pipeline_emits_clip_on_event_closed():
    with patch("src.engine.clip_generator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        pipeline = MasterPipeline(
            clip_source="dummy.mp4",
            output_dir="output/clips"
        )
        
        # Force the state machine into ACTIVE state
        pipeline.state_machine.current_event.state = "ACTIVE"
        pipeline.state_machine.current_event.start_pts = 5.0
        pipeline.state_machine.current_event.below_close_since = 5.0
        
        # Send weak signal for > CLOSE_COOLDOWN seconds to trigger CLOSED
        audio_chunk = np.zeros(16000 * 5)
        chat_msgs = []
        pipeline.process_chunk(pts=11.0, audio_data=audio_chunk, chat_messages=chat_msgs)
        
        # Event should now be CLOSED and FFmpeg called once
        assert pipeline.state_machine.current_event.state == "CLOSED"
        mock_run.assert_called_once()
