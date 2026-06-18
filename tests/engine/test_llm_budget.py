from src.engine.llm_budget import LLMBudgetTracker


def test_budget_blocks_after_cap(tmp_path):
    tracker = LLMBudgetTracker(daily_cap=2, state_path=str(tmp_path / "budget.json"))
    assert tracker.can_call()
    tracker.record_call("boundary", "ok")
    tracker.record_call("boundary", "ok")
    assert not tracker.can_call()
    assert tracker.remaining == 0


def test_budget_resets_new_day(tmp_path):
    day = {"value": "2026-06-18"}

    tracker = LLMBudgetTracker(
        daily_cap=2,
        state_path=str(tmp_path / "budget.json"),
        today_fn=lambda: day["value"],
    )
    tracker.record_call("boundary", "ok")
    tracker.record_call("boundary", "ok")
    assert not tracker.can_call()

    day["value"] = "2026-06-19"
    tracker.reset_if_new_day()
    assert tracker.can_call()
    assert tracker.remaining == 2
