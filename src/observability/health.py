import time


def check_liveness() -> dict:
    return {"status": "ok"}


def check_readiness(
    db_ok: bool,
    nodes: list[dict],
    max_stale_sec: float = 60,
) -> dict:
    now = time.time()
    ready = db_ok and all(
        node.get("healthy") is True
        and (now - node.get("last_heartbeat_ts", 0.0)) <= max_stale_sec
        for node in nodes
    )
    return {
        "ready": ready,
        "status": "ok" if ready else "degraded",
        "db": db_ok,
        "nodes": nodes,
    }
