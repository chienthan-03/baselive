import time

from src.observability.health import check_liveness, check_readiness


def test_liveness_always_ok():
    assert check_liveness() == {"status": "ok"}


def test_readiness_returns_not_ready_when_nodes_stale():
    nodes = [{"node_id": "node-0", "last_heartbeat_ts": 0.0, "healthy": False}]
    result = check_readiness(db_ok=True, nodes=nodes, max_stale_sec=60)
    assert result["ready"] is False


def test_readiness_returns_ready_when_db_ok_and_nodes_healthy():
    nodes = [
        {
            "node_id": "node-0",
            "last_heartbeat_ts": time.time(),
            "healthy": True,
        }
    ]
    result = check_readiness(db_ok=True, nodes=nodes, max_stale_sec=60)
    assert result["ready"] is True
    assert result["status"] == "ok"
    assert result["db"] is True
    assert result["nodes"] == nodes
