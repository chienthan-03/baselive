import json

import pytest

from src.db.database import Database
from src.engine.feedback_learner import FeedbackLearner


@pytest.fixture
def test_db():
    db = Database(db_path=":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def config_paths(tmp_path):
    stream_config = tmp_path / "stream_config.json"
    global_prior = tmp_path / "global_prior.json"
    stream_config.write_text("{}", encoding="utf-8")
    global_prior.write_text(
        json.dumps(
            {
                "open_thr": 0.5,
                "confirm_thr": 0.65,
                "close_thr": 0.25,
                "peak_thr": 0.8,
                "audio_energy_mean": 0.05,
                "chat_volume_mean": 8.0,
                "speaking_rate_mean": 3.5,
            }
        ),
        encoding="utf-8",
    )
    return stream_config, global_prior


def _insert_modify_feedback(db: Database, stream_id: str, start_delta: float, count: int):
    for i in range(count):
        h_id = db.insert_highlight(
            stream_id=stream_id,
            start_pts=100.0,
            end_pts=130.0,
            score=0.8,
            ai_start_pts=100.0,
            ai_end_pts=130.0,
        )
        db.insert_feedback(
            highlight_id=h_id,
            stream_id=stream_id,
            action="MODIFY",
            ai_start_pts=100.0,
            ai_end_pts=130.0,
            editor_start_pts=100.0 + start_delta,
            editor_end_pts=130.0,
            start_delta_sec=start_delta,
            end_delta_sec=0.0,
        )


@pytest.fixture
def db_few_feedback(test_db):
    _insert_modify_feedback(test_db, "stream_a", start_delta=-3.0, count=5)
    return test_db


@pytest.fixture
def db_enough_modify_feedback(test_db):
    _insert_modify_feedback(test_db, "stream_a", start_delta=-3.0, count=10)
    return test_db


def test_learner_skips_when_insufficient_data(db_few_feedback, config_paths):
    stream_config_path, global_prior_path = config_paths
    learner = FeedbackLearner(
        db_few_feedback,
        stream_config_path=stream_config_path,
        global_prior_path=global_prior_path,
    )
    result = learner.run_daily()
    assert result.applied is False


def test_learner_adjusts_pre_roll(db_enough_modify_feedback, config_paths):
    stream_config_path, global_prior_path = config_paths
    learner = FeedbackLearner(
        db_enough_modify_feedback,
        stream_config_path=stream_config_path,
        global_prior_path=global_prior_path,
    )
    result = learner.run_daily()
    assert result.applied is True
    assert result.pre_roll_delta != 0

    saved = json.loads(stream_config_path.read_text(encoding="utf-8"))
    assert saved["stream_a"]["pre_roll"] > 10.0
