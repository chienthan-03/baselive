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


def test_active_event_force_closes_at_120s():
    """Event ACTIVE longer than 120s must be force-closed."""
    from src.engine.state_machine import StateMachine
    from src.core.models import SignalSnapshot

    sm = StateMachine()
    # Manufacture a snapshot that opens and confirms the event
    def make_snapshot(pts, score):
        s = SignalSnapshot(pts=pts, audio_energy=score, composite_score=score)
        return s

    # Open and confirm
    sm.process(make_snapshot(0.0, 0.6))   # OPENING
    sm.process(make_snapshot(1.0, 0.7))   # ACTIVE

    assert sm.current_event.state == "ACTIVE"

    # Simulate 121 seconds passing with score staying above close_thr
    sm.process(make_snapshot(121.0, 0.7))

    assert sm.current_event.state == "CLOSED", (
        f"Expected CLOSED after 121s, got {sm.current_event.state}"
    )

