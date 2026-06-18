import logging

from src.observability.logging_context import stream_logger


def test_stream_logger_includes_context(caplog):
    log = stream_logger(__name__, stream_id="s1", platform="tiktok", node_id="node-0")
    with caplog.at_level(logging.INFO):
        log.info("test message")
    record = caplog.records[0]
    assert record.stream_id == "s1"
    assert record.platform == "tiktok"
    assert record.node_id == "node-0"
