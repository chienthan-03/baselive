"""Structured logging context for stream-scoped log records."""
import logging

# TODO(Task 8): OrchestratorService will use stream_logger for node-level context.


def stream_logger(
    name: str,
    stream_id: str,
    platform: str = "tiktok",
    node_id: str = "node-0",
) -> logging.LoggerAdapter:
    """Return a logger adapter that injects stream context into every log record."""
    base_logger = logging.getLogger(name)
    extra = {
        "stream_id": stream_id,
        "platform": platform,
        "node_id": node_id,
    }
    return logging.LoggerAdapter(base_logger, extra)
