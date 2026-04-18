from core.RecoveryEngine import RecoveryEngine


def dummy_recovery_action(error):
    dummy_recovery_action.called = True
    dummy_recovery_action.last_error = str(error)


def test_recovery_engine():
    engine = RecoveryEngine()
    dummy_recovery_action.called = False
    engine.register_action(dummy_recovery_action)
    try:
        raise ValueError("Test error")
    except Exception as e:
        engine.detect_and_recover(e)
    assert dummy_recovery_action.called
    assert dummy_recovery_action.last_error == "Test error"
