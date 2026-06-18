from src.engine.state_machine import StateMachine
from src.core.models import SignalSnapshot, ThresholdSet


def test_state_machine_forced_close_at_max_duration():
    sm = StateMachine()
    sm.current_event.state = "ACTIVE"
    sm.current_event.start_pts = 0.0
    sm.process(SignalSnapshot(pts=601.0, composite_score=0.9))
    assert sm.current_event.state == "CLOSED"


def test_state_machine_uses_dynamic_thresholds():
    sm = StateMachine()
    thresholds = ThresholdSet(open_thr=0.7, confirm_thr=0.8, close_thr=0.2, peak_thr=0.9)
    sm.process(SignalSnapshot(pts=1.0, composite_score=0.65), thresholds=thresholds)
    assert sm.current_event.state == "IDLE"


def test_state_machine_appends_signals():
    sm = StateMachine()
    sm.process(SignalSnapshot(pts=1.0, composite_score=0.9))
    assert len(sm.current_event.signals) >= 1
