import pytest

from src.db.database import Database
from src.ingestion.stream_registry import StreamInfo, StreamRegistry


@pytest.fixture
def test_db():
    db = Database(db_path=":memory:")
    db.init_db()
    yield db
    db.close()


def test_register_and_list_active():
    reg = StreamRegistry()
    info = StreamInfo("s1", "tiktok", "http://x", "node-0", 100.0, "RUNNING")
    reg.register(info)
    assert len(reg.list_active()) == 1


def test_stream_registry_sync_from_db(test_db):
    test_db.upsert_stream(
        "s1",
        platform="tiktok",
        url="http://x",
        status="RUNNING",
        node_id="node-0",
        started_at=100.0,
    )
    reg = StreamRegistry(db=test_db)
    reg.sync_from_db()
    assert reg.get("s1").status == "RUNNING"
