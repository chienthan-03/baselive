import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import error, request

from src.core.models import AmbiguousPair, BoundaryResult, EventCandidate

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.0-flash-001"
MAX_CALLS_PER_HOUR = 10
MIN_GAP_SEC = 30
DAILY_BUDGET_USD = 5.0
ESTIMATED_COST_PER_CALL = 0.02


@dataclass
class LLMRefineResult:
    refined_start_pts: float
    refined_end_pts: float
    content_type: str
    confidence: float
    reasoning: str = ""


@dataclass
class LLMOverlapResult:
    decision: str
    confidence: float
    reasoning: str = ""


class LLMGate:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY")
        self._model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
        self._call_timestamps: List[float] = []
        self._last_call_time: Optional[float] = None
        self._daily_spend_usd: float = 0.0
        self._daily_spend_date: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def should_refine_boundary(self, event: EventCandidate, boundary: BoundaryResult) -> bool:
        if not self.enabled:
            return False
        duration = boundary.resolution_pts - boundary.trigger_pts
        if event.peak_score > 0.7:
            return True
        if duration > 180:
            return True
        return False

    def refine_boundary(
        self,
        boundary: BoundaryResult,
        transcript: str,
        signals_summary: Dict[str, Any],
        language: str = "vi",
        force: bool = False,
    ) -> Optional[LLMRefineResult]:
        if not self.enabled:
            return None
        if not force and not self._can_call():
            return None

        payload = {
            "task": "refine_highlight_boundary",
            "transcript": transcript,
            "signals_summary": signals_summary,
            "current_boundary": {
                "start": boundary.trigger_pts,
                "end": boundary.resolution_pts,
            },
            "language": language,
        }

        try:
            parsed = self._call_openrouter(payload)
            self._record_call()
            return LLMRefineResult(
                refined_start_pts=float(parsed["refined_start_pts"]),
                refined_end_pts=float(parsed["refined_end_pts"]),
                content_type=str(parsed.get("content_type", "unknown")),
                confidence=float(parsed.get("confidence", 0.0)),
                reasoning=str(parsed.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLMGate refine_boundary failed: %s", exc)
            return None

    def resolve_overlap(self, pair: AmbiguousPair) -> Optional[LLMOverlapResult]:
        if not self.enabled:
            return None
        if not self._can_call():
            return None

        payload = {
            "task": "resolve_overlap",
            "event_a": {
                "start_pts": pair.event_a.start_pts,
                "end_pts": pair.event_a.end_pts,
                "peak_pts": pair.event_a.peak_pts,
                "peak_score": pair.event_a.peak_score,
                "keywords": pair.event_a.keywords,
                "transcript_excerpt": pair.event_a.transcript_excerpt,
            },
            "event_b": {
                "start_pts": pair.event_b.start_pts,
                "end_pts": pair.event_b.end_pts,
                "peak_pts": pair.event_b.peak_pts,
                "peak_score": pair.event_b.peak_score,
                "keywords": pair.event_b.keywords,
                "transcript_excerpt": pair.event_b.transcript_excerpt,
            },
            "similarity": pair.similarity,
        }

        try:
            parsed = self._call_openrouter(payload)
            self._record_call()
            return LLMOverlapResult(
                decision=str(parsed["decision"]),
                confidence=float(parsed.get("confidence", 0.0)),
                reasoning=str(parsed.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLMGate resolve_overlap failed: %s", exc)
            return None

    def _can_call(self) -> bool:
        if not self.enabled:
            return False

        now = time.time()
        self._reset_daily_budget_if_needed(now)

        if self._daily_spend_usd + ESTIMATED_COST_PER_CALL > DAILY_BUDGET_USD:
            logger.warning("LLMGate daily budget exceeded")
            return False

        self._prune_old_calls(now)
        if len(self._call_timestamps) >= MAX_CALLS_PER_HOUR:
            logger.warning("LLMGate hourly rate limit exceeded")
            return False

        if self._last_call_time is not None and now - self._last_call_time < MIN_GAP_SEC:
            logger.warning("LLMGate min gap not elapsed")
            return False

        return True

    def _record_call(self) -> None:
        now = time.time()
        self._reset_daily_budget_if_needed(now)
        self._prune_old_calls(now)
        self._call_timestamps.append(now)
        self._last_call_time = now
        self._daily_spend_usd += ESTIMATED_COST_PER_CALL

    def _reset_daily_budget_if_needed(self, now: float) -> None:
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self._daily_spend_date != today:
            self._daily_spend_date = today
            self._daily_spend_usd = 0.0

    def _prune_old_calls(self, now: float) -> None:
        cutoff = now - 3600
        self._call_timestamps = [ts for ts in self._call_timestamps if ts > cutoff]

    def _call_openrouter(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a livestream highlight editor. "
                        "Respond with valid JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }

        req = request.Request(
            OPENROUTER_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=30) as resp:
                response_body = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(f"OpenRouter HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc.reason}") from exc

        content = response_body["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return json.loads(content)
        return content
