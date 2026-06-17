from src.core.models import SignalSnapshot

class SignalAggregator:
    def __init__(self, w_audio=0.2, w_stt=0.4, w_chat=0.4):
        self.w_audio = w_audio
        self.w_stt = w_stt
        self.w_chat = w_chat

    def compute_score(self, snapshot: SignalSnapshot) -> float:
        # Audio component
        s_audio = 1.0 if snapshot.audio_energy_spike else 0.0
        
        # STT component
        s_stt = snapshot.sentiment_shift
        
        # Chat component
        s_chat = snapshot.chat_volume_spike
        
        score = (s_audio * self.w_audio) + (s_stt * self.w_stt) + (s_chat * self.w_chat)
        
        # Cập nhật trực tiếp vào snapshot
        snapshot.composite_score = score
        return score
