import re
from typing import List

from src.core.models import TranscriptResult


class STTAnalyzer:
    SHOCK_KEYWORDS = ["trời ơi", "ôi", "omg", "wth", "what"]
    POSITIVE_KEYWORDS = ["hay", "tuyệt", "ngon", "đẹp", "vui", "thích", "yêu", "tốt", "giỏi"]
    NEGATIVE_KEYWORDS = ["tệ", "dở", "kinh", "ghét", "buồn", "chán", "xấu", "tồi", "đau"]

    def analyze(self, result: TranscriptResult, duration_sec: float) -> dict:
        text = result.text.strip()
        text_lower = text.lower()

        words = text.split()
        word_count = len(words)
        speaking_rate = (word_count * 1.5 / duration_sec) if duration_sec > 0 else 0.0

        keyword_triggered = self._match_keywords(text_lower, self.SHOCK_KEYWORDS)
        sentiment_shift = self._sentiment_shift(text_lower)
        sentence_rate = self._sentence_rate(text, duration_sec)

        return {
            "speaking_rate": speaking_rate,
            "keyword_triggered": keyword_triggered,
            "sentiment_shift": sentiment_shift,
            "sentence_rate": sentence_rate,
        }

    def _match_keywords(self, text_lower: str, keywords: List[str]) -> List[str]:
        triggered = []
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in text_lower and kw not in triggered:
                triggered.append(kw)
        return triggered

    def _sentiment_shift(self, text_lower: str) -> float:
        positive = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text_lower)
        negative = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text_lower)
        total = positive + negative
        if total == 0:
            return 0.0
        shift = (positive - negative) / total
        return max(-1.0, min(1.0, shift))

    def _sentence_rate(self, text: str, duration_sec: float) -> float:
        if duration_sec <= 0:
            return 0.0
        sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
        sentence_count = max(len(sentences), 1) if text.strip() else 0
        return sentence_count * 10.0 / duration_sec
