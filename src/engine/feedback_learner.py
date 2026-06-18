import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.db.database import Database

logger = logging.getLogger(__name__)

_DEFAULT_STREAM_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "stream_config.json"
)
_DEFAULT_GLOBAL_PRIOR_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "global_prior.json"
)

DEFAULT_PRE_ROLL = 10.0
DEFAULT_POST_ROLL = 5.0
SMOOTHING_OLD_WEIGHT = 0.7
SMOOTHING_NEW_WEIGHT = 0.3
OPEN_THR_BUMP_FACTOR = 0.1


@dataclass
class LearningResult:
    applied: bool
    pre_roll_delta: float = 0.0
    post_roll_delta: float = 0.0
    open_thr_delta: float = 0.0


def _smooth(old: float, learned: float) -> float:
    return SMOOTHING_OLD_WEIGHT * old + SMOOTHING_NEW_WEIGHT * learned


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


class FeedbackLearner:
    MIN_FEEDBACK_ENTRIES = 10

    def __init__(
        self,
        db: Database,
        *,
        stream_config_path: Optional[Path] = None,
        global_prior_path: Optional[Path] = None,
    ):
        self.db = db
        self.stream_config_path = stream_config_path or _DEFAULT_STREAM_CONFIG_PATH
        self.global_prior_path = global_prior_path or _DEFAULT_GLOBAL_PRIOR_PATH

    def _load_json(self, path: Path) -> Dict:
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: Path, data: Dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    def run_daily(self) -> LearningResult:
        feedback = self.db.get_feedback_since(hours=24)
        if len(feedback) < self.MIN_FEEDBACK_ENTRIES:
            logger.info(
                "Skipping learning: %d feedback entries (< %d)",
                len(feedback),
                self.MIN_FEEDBACK_ENTRIES,
            )
            return LearningResult(applied=False)

        stream_config = self._load_json(self.stream_config_path)
        global_prior = self._load_json(self.global_prior_path)

        old_open_thr = float(global_prior.get("open_thr", 0.5))
        false_positive_count = sum(
            1
            for entry in feedback
            if entry.get("action") == "REJECT"
            and entry.get("reject_reason") == "false_positive"
        )
        false_positive_rate = false_positive_count / len(feedback)
        learned_open_thr = old_open_thr + false_positive_rate * OPEN_THR_BUMP_FACTOR
        new_open_thr = _smooth(old_open_thr, learned_open_thr)
        global_prior["open_thr"] = new_open_thr
        open_thr_delta = new_open_thr - old_open_thr

        pre_roll_deltas: List[float] = []
        post_roll_deltas: List[float] = []

        by_stream: Dict[str, List[Dict]] = {}
        for entry in feedback:
            by_stream.setdefault(entry["stream_id"], []).append(entry)

        for stream_id, entries in by_stream.items():
            modify_entries = [e for e in entries if e.get("action") == "MODIFY"]
            start_deltas = [
                float(e["start_delta_sec"])
                for e in modify_entries
                if e.get("start_delta_sec") is not None
            ]
            end_deltas = [
                float(e["end_delta_sec"])
                for e in modify_entries
                if e.get("end_delta_sec") is not None
            ]

            stream_entry = stream_config.get(stream_id, {})
            old_pre_roll = float(stream_entry.get("pre_roll", DEFAULT_PRE_ROLL))
            old_post_roll = float(stream_entry.get("post_roll", DEFAULT_POST_ROLL))

            avg_start_delta = _mean(start_deltas)
            avg_end_delta = _mean(end_deltas)

            learned_pre_roll = old_pre_roll - avg_start_delta
            learned_post_roll = old_post_roll + avg_end_delta

            new_pre_roll = _smooth(old_pre_roll, learned_pre_roll)
            new_post_roll = _smooth(old_post_roll, learned_post_roll)

            pre_roll_deltas.append(new_pre_roll - old_pre_roll)
            post_roll_deltas.append(new_post_roll - old_post_roll)

            stream_config[stream_id] = {
                "pre_roll": new_pre_roll,
                "post_roll": new_post_roll,
                "open_thr": new_open_thr,
            }

        self._write_json(self.stream_config_path, stream_config)
        self._write_json(self.global_prior_path, global_prior)

        result = LearningResult(
            applied=True,
            pre_roll_delta=_mean(pre_roll_deltas),
            post_roll_delta=_mean(post_roll_deltas),
            open_thr_delta=open_thr_delta,
        )
        logger.info("Applied daily learning: %s", result)
        return result
