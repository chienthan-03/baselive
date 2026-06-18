from src.engine.state_machine import StateMachine
from src.core.models import SignalSnapshot


def test_state_machine_forced_close_at_max_duration():
    sm = StateMachine()
    sm.current_event.state = "ACTIVE"
    sm.current_event.start_pts = 0.0
    sm.process(SignalSnapshot(pts=601.0, composite_score=0.9))
    assert sm.current_event.state == "CLOSED"


def test_state_machine_appends_signals():
    sm = StateMachine()
    sm.process(SignalSnapshot(pts=1.0, composite_score=0.9))
    assert len(sm.current_event.signals) >= 1
