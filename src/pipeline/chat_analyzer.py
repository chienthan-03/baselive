from typing import List, Dict

class ChatAnalyzer:
    def __init__(self):
        self.keywords = ["haha", "hay", "ảo", "cháy", "vcl", "clm", "lol"]
        self.baseline_volume = 1.0
        
    def analyze_batch(self, messages: List[Dict]) -> dict:
        volume = len(messages)
        
        # Simple volume spike detection
        is_spike = volume > (self.baseline_volume * 2)
        self.baseline_volume = 0.9 * self.baseline_volume + 0.1 * max(1, volume)
        
        triggered = []
        for m in messages:
            text = m.get("msg", "").lower()
            for kw in self.keywords:
                if kw in text and kw not in triggered:
                    triggered.append(kw)
                    
        return {
            "chat_volume_spike": 1.0 if is_spike else 0.0,
            "keyword_triggered": triggered,
            "raw_volume": volume
        }
