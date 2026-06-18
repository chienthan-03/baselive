"""CLI entry point for the daily feedback learning batch job."""

from src.db.database import Database
from src.engine.feedback_learner import FeedbackLearner, LearningResult


def run() -> LearningResult:
    db = Database()
    db.init_db()
    try:
        learner = FeedbackLearner(db)
        return learner.run_daily()
    finally:
        db.close()


def main() -> None:
    result = run()
    print(
        f"applied={result.applied} "
        f"pre_roll_delta={result.pre_roll_delta:.4f} "
        f"post_roll_delta={result.post_roll_delta:.4f} "
        f"open_thr_delta={result.open_thr_delta:.4f}"
    )


if __name__ == "__main__":
    main()
