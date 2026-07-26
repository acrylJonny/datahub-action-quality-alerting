import pytest

from action_quality_alerting.config import RetryConfig
from action_quality_alerting.retry import is_transient, retry_call


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _HTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = _Resp(status_code)


class _Timeout(Exception):
    pass


# _Timeout's class name isn't in the transient set; use the real-ish name.
_Timeout.__name__ = "ReadTimeout"


def test_is_transient_by_status():
    assert is_transient(_HTTPError(500))
    assert is_transient(_HTTPError(503))
    assert is_transient(_HTTPError(429))
    assert not is_transient(_HTTPError(400))
    assert not is_transient(_HTTPError(404))


def test_is_transient_by_exception_name():
    assert is_transient(_Timeout())
    assert not is_transient(ValueError("bad template"))


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _HTTPError(503)
        return "ok"

    result = retry_call(fn, retry=RetryConfig(max_attempts=4), sleep=lambda _s: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise _HTTPError(500)

    with pytest.raises(_HTTPError):
        retry_call(fn, retry=RetryConfig(max_attempts=3), sleep=lambda _s: None)
    assert calls["n"] == 3


def test_retry_does_not_retry_permanent_error():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise _HTTPError(400)

    with pytest.raises(_HTTPError):
        retry_call(fn, retry=RetryConfig(max_attempts=5), sleep=lambda _s: None)
    assert calls["n"] == 1
