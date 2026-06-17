import pytest
import numpy as np
from src.buffer.circular_buffer import AudioRingBuffer, VideoBuffer, TranscriptBuffer, ChatBuffer

def test_audio_ring_buffer():
    buffer = AudioRingBuffer(capacity_sec=10, sample_rate=16000)
    data = np.ones(16000 * 5)
    buffer.write(data, start_pts=0.0)
    read_data = buffer.read(start_pts=0.0, duration_sec=2.0)
    assert len(read_data) == 32000

def test_list_buffers():
    v_buf = VideoBuffer(capacity_sec=600)
    t_buf = TranscriptBuffer(capacity_sec=900)
    c_buf = ChatBuffer(capacity_sec=900)
    
    v_buf.add_item({"path": "seg1.ts"}, 10.0)
    assert len(v_buf.items) == 1
    
    t_buf.add_item({"word": "hello"}, 10.5)
    assert len(t_buf.items) == 1
    
    c_buf.add_item({"msg": "hi"}, 11.0)
    assert len(c_buf.items) == 1
    
def test_pinning_logic():
    c_buf = ChatBuffer(capacity_sec=10)
    c_buf.pin_range(0.0, 5.0)
    c_buf.add_item({"msg": "pinned"}, 2.0)
    c_buf.add_item({"msg": "new"}, 50.0)
    assert len([i for i in c_buf.items if i['item']['msg'] == 'pinned']) == 1
