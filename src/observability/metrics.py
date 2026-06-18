import threading

from prometheus_client import Counter, Gauge, Histogram, REGISTRY, generate_latest


class MetricsCollector:
    """Singleton metrics registry. Thread-safe."""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        if getattr(self, "_init_done", False):
            return
        self._init_done = True

        self.streams_started_total = Counter(
            "streams_started_total",
            "Total number of streams started",
            ["platform"],
        )
        self.streams_stopped_total = Counter(
            "streams_stopped_total",
            "Total number of streams stopped",
            ["platform", "reason"],
        )
        self.highlights_created_total = Counter(
            "highlights_created_total",
            "Total number of highlights created",
            ["type"],
        )
        self.llm_calls_total = Counter(
            "llm_calls_total",
            "Total number of LLM calls",
            ["gate", "status"],
        )
        self.pipeline_errors_total = Counter(
            "pipeline_errors_total",
            "Total number of pipeline errors",
            ["stage"],
        )

        self.streams_active = Gauge(
            "streams_active",
            "Number of currently active streams",
            ["platform", "node_id"],
        )
        self.worker_node_healthy = Gauge(
            "worker_node_healthy",
            "Worker node health status (1=healthy, 0=unhealthy)",
            ["node_id"],
        )
        self.llm_budget_remaining = Gauge(
            "llm_budget_remaining",
            "Remaining LLM calls allowed today",
        )

        self.pipeline_chunk_duration_sec = Histogram(
            "pipeline_chunk_duration_sec",
            "Pipeline chunk processing duration in seconds",
        )
        self.stt_transcribe_duration_sec = Histogram(
            "stt_transcribe_duration_sec",
            "STT transcription duration in seconds",
        )
        self.clip_generate_duration_sec = Histogram(
            "clip_generate_duration_sec",
            "Clip generation duration in seconds",
        )

    def inc_stream_started(self, platform: str) -> None:
        self.streams_started_total.labels(platform=platform).inc()

    def inc_stream_stopped(self, platform: str, reason: str) -> None:
        self.streams_stopped_total.labels(platform=platform, reason=reason).inc()

    def inc_highlight(self, highlight_type: str) -> None:
        self.highlights_created_total.labels(type=highlight_type).inc()

    def inc_llm_call(self, gate: str, status: str) -> None:
        self.llm_calls_total.labels(gate=gate, status=status).inc()

    def set_llm_budget_remaining(self, remaining: int) -> None:
        self.llm_budget_remaining.set(float(remaining))

    def inc_pipeline_error(self, stage: str) -> None:
        self.pipeline_errors_total.labels(stage=stage).inc()

    def observe_chunk(self, duration_sec: float, stream_id: str) -> None:
        self.pipeline_chunk_duration_sec.observe(duration_sec)

    def observe_stt(self, duration_sec: float) -> None:
        self.stt_transcribe_duration_sec.observe(duration_sec)

    def observe_clip_gen(self, duration_sec: float) -> None:
        self.clip_generate_duration_sec.observe(duration_sec)

    def set_streams_active(self, count: int, platform: str, node_id: str) -> None:
        self.streams_active.labels(platform=platform, node_id=node_id).set(count)

    def set_node_healthy(self, node_id: str, healthy: bool) -> None:
        self.worker_node_healthy.labels(node_id=node_id).set(1.0 if healthy else 0.0)

    def export_text(self) -> str:
        return generate_latest(REGISTRY).decode("utf-8")
