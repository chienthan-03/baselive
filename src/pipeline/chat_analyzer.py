from collections import Counter, defaultdict
from typing import Dict, List, Optional

EMOJI_FUNNY = {"😂", "🤣", "💀", "😆"}
EMOJI_SHOCK = {"😱", "😨", "🤯"}
EMOJI_LOVE = {"❤️", "😍", "🥰"}
EMOJI_SAD = {"😢", "😭", "💔"}

KEYWORD_CLUSTERS = {
    "HYPE": ["gg", "clutch", "pro", "slay", "queen"],
    "SHOCK": ["ôi", "trời ơi", "wth", "omg", "what"],
    "DRAMA": ["drama", "beef", "cancel", "exposed"],
}


class ChatAnalyzer:
    def __init__(self):
        self.keywords = ["haha", "hay", "ảo", "cháy", "vcl", "clm", "lol"]
        self.baseline_volume = 1.0

    def _normalize_text(self, m: Dict) -> str:
        return m.get("content") or m.get("msg", "")

    def _filter_spam(self, messages: List[Dict]) -> List[Dict]:
        text_counts: Counter = Counter()
        for m in messages:
            if not m.get("username"):
                continue
            text = self._normalize_text(m).strip().lower()
            if text:
                text_counts[text] += 1
        spam_texts = {text for text, count in text_counts.items() if count > 3}
        filtered = [
            m
            for m in messages
            if not m.get("username")
            or self._normalize_text(m).strip().lower() not in spam_texts
        ]

        by_user: Dict[str, List[Dict]] = defaultdict(list)
        for m in filtered:
            username = m.get("username", "")
            if username:
                by_user[username].append(m)

        kept: List[Dict] = []
        dropped_ids = set()
        for user_msgs in by_user.values():
            sorted_msgs = sorted(user_msgs, key=lambda m: m.get("pts", 0.0))
            window: List[Dict] = []
            for m in sorted_msgs:
                pts = m.get("pts", 0.0)
                window = [w for w in window if pts - w.get("pts", 0.0) <= 5.0]
                if len(window) >= 5:
                    dropped_ids.add(id(m))
                else:
                    window.append(m)

        for m in filtered:
            username = m.get("username", "")
            if not username or id(m) not in dropped_ids:
                kept.append(m)

        return kept

    def _score_emojis(self, text: str) -> Dict[str, float]:
        scores = {"funny": 0.0, "shock": 0.0, "love": 0.0, "sad": 0.0}
        for char in text:
            if char in EMOJI_FUNNY:
                scores["funny"] += 1.0
            elif char in EMOJI_SHOCK:
                scores["shock"] += 1.0
            elif char in EMOJI_LOVE:
                scores["love"] += 1.0
            elif char in EMOJI_SAD:
                scores["sad"] += 1.0
        return scores

    def _detect_gift(self, messages: List[Dict]) -> Optional[Dict]:
        for m in messages:
            if m.get("event_type") == "GIFT":
                return {
                    "value": m.get("gift_value", 0),
                    "username": m.get("username", ""),
                }
        return None

    def _detect_keyword_cluster(self, messages: List[Dict]) -> Optional[str]:
        cluster_counts = {name: 0 for name in KEYWORD_CLUSTERS}
        for m in messages:
            text = self._normalize_text(m).lower()
            for cluster, keywords in KEYWORD_CLUSTERS.items():
                if any(kw in text for kw in keywords):
                    cluster_counts[cluster] += 1

        best_cluster = None
        best_count = 0
        for cluster, count in cluster_counts.items():
            if count >= 3 and count > best_count:
                best_cluster = cluster
                best_count = count
        return best_cluster

    def analyze_batch(self, messages: List[Dict]) -> dict:
        filtered = self._filter_spam(messages)
        volume = len(filtered)

        is_spike = volume > (self.baseline_volume * 2)
        self.baseline_volume = 0.9 * self.baseline_volume + 0.1 * max(1, volume)

        triggered = []
        emoji_totals = {"funny": 0.0, "shock": 0.0, "love": 0.0, "sad": 0.0}
        for m in filtered:
            text = self._normalize_text(m).lower()
            for kw in self.keywords:
                if kw in text and kw not in triggered:
                    triggered.append(kw)
            for category, score in self._score_emojis(self._normalize_text(m)).items():
                emoji_totals[category] += score

        msg_count = max(1, len(filtered))
        chat_emoji_scores = {
            category: total / msg_count for category, total in emoji_totals.items()
        }

        return {
            "chat_volume_spike": 1.0 if is_spike else 0.0,
            "keyword_triggered": triggered,
            "raw_volume": volume,
            "chat_emoji_scores": chat_emoji_scores,
            "gift_event": self._detect_gift(messages),
            "chat_keyword_cluster": self._detect_keyword_cluster(filtered),
        }
