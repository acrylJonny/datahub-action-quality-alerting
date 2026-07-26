from action_quality_alerting.dedup import is_new_failure


def _assertion(*result_types: str) -> dict:
    # runEvents are newest-first: result_types[0] is the current run.
    events = [
        {"result": {"type": t}, "timestampMillis": 1000 - i} for i, t in enumerate(result_types)
    ]
    return {"runEvents": {"runEvents": events}}


def test_first_ever_run_is_new_failure():
    assert is_new_failure(_assertion("FAILURE"), 1000) is True


def test_success_to_failure_is_new():
    assert is_new_failure(_assertion("FAILURE", "SUCCESS"), 1000) is True


def test_consecutive_failures_not_new():
    assert is_new_failure(_assertion("FAILURE", "FAILURE"), 1000) is False


def test_error_then_failure_not_new():
    # ERROR is treated as a failing state, so it does not re-trigger.
    assert is_new_failure(_assertion("FAILURE", "ERROR"), 1000) is False
