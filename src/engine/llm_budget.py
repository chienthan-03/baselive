import json
import os
import threading
from datetime import date
from typing import Callable, Optional

DEFAULT_STATE_PATH = "config/llm_budget.json"
DEFAULT_DAILY_CAP = 100


class LLMBudgetTracker:
    """Tracks daily LLM call count against a configurable cap."""

    def __init__(
        self,
        daily_cap: Optional[int] = None,
        state_path: str = DEFAULT_STATE_PATH,
        today_fn: Optional[Callable[[], str]] = None,
    ):
        self._state_path = state_path
        self._lock = threading.Lock()
        self._today_fn = today_fn or (lambda: date.today().isoformat())
        self._daily_cap = daily_cap if daily_cap is not None else DEFAULT_DAILY_CAP
        self._date = self._today_fn()
        self._count = 0
        self._load_state()

    def _load_state(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        if "daily_cap" in data:
            self._daily_cap = int(data["daily_cap"])
        self._date = str(data.get("date", self._date))
        self._count = int(data.get("count", 0))
        self.reset_if_new_day()

    def _save_state(self) -> None:
        directory = os.path.dirname(self._state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "daily_cap": self._daily_cap,
            "date": self._date,
            "count": self._count,
        }
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def reset_if_new_day(self) -> None:
        today = self._today_fn()
        if self._date != today:
            self._date = today
            self._count = 0
            self._save_state()

    def can_call(self) -> bool:
        with self._lock:
            self.reset_if_new_day()
            return self._count < self._daily_cap

    @property
    def remaining(self) -> int:
        with self._lock:
            self.reset_if_new_day()
            return max(0, self._daily_cap - self._count)

    def record_call(self, gate: str, status: str) -> None:
        del gate, status  # reserved for metrics/logging at call site
        with self._lock:
            self.reset_if_new_day()
            self._count += 1
            self._save_state()
