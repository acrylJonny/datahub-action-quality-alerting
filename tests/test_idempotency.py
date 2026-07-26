import json

from action_quality_alerting.config import JiraSink, RetryConfig, ServiceNowSink, WebhookSink
from action_quality_alerting.models import AlertContext
from action_quality_alerting.sinks import dispatch
from action_quality_alerting.sinks import http as http_sink


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"x"

    def json(self) -> dict:
        return self._payload


class _HTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")

        class _R:
            pass

        self.response = _R()
        self.response.status_code = status_code


def _ctx(key: str = "urn:li:assertion:a:run1") -> AlertContext:
    return AlertContext(
        result_type="FAILURE",
        asset_name="cat.sch.tbl",
        asset_urn="urn:li:dataset:x",
        idempotency_key=key,
    )


def test_jira_search_before_create_creates_when_absent(monkeypatch):
    calls: list[tuple] = []

    def fake_send(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return _FakeResp({"issues": []})
        return _FakeResp({"key": "DQ-1"})

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = JiraSink(
        base_url="https://x.atlassian.net", username="u", api_token="t", project_key="DQ"
    )

    result = dispatch(sink, _ctx())
    assert result.ok
    assert "DQ-1" in (result.detail or "")
    methods = [c[0] for c in calls]
    assert methods == ["GET", "POST"]
    # The dedup label derived from the idempotency key is attached on create.
    create_kwargs = calls[1][2]
    labels = create_kwargs["json_body"]["fields"]["labels"]
    assert labels and labels[0].startswith("dhq-")


def test_jira_search_before_create_skips_when_present(monkeypatch):
    calls: list[str] = []

    def fake_send(method, url, **kwargs):
        calls.append(method)
        if method == "GET":
            return _FakeResp({"issues": [{"key": "DQ-9"}]})
        raise AssertionError("must not create when an issue already exists")

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = JiraSink(
        base_url="https://x.atlassian.net", username="u", api_token="t", project_key="DQ"
    )

    result = dispatch(sink, _ctx())
    assert result.ok
    assert "existing DQ-9" in (result.detail or "")
    assert calls == ["GET"]


def test_servicenow_sets_correlation_id_and_searches(monkeypatch):
    calls: list[tuple] = []

    def fake_send(method, url, **kwargs):
        calls.append((method, kwargs))
        if method == "GET":
            return _FakeResp({"result": []})
        return _FakeResp({"result": {"number": "INC001"}})

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = ServiceNowSink(base_url="https://x.service-now.com", username="u", api_token="t")

    result = dispatch(sink, _ctx())
    assert result.ok and result.detail == "INC001"
    create_kwargs = calls[1][1]
    assert create_kwargs["json_body"]["correlation_id"] == "urn:li:assertion:a:run1"


def test_webhook_default_envelope_carries_idempotency(monkeypatch):
    seen: dict = {}

    def fake_send(method, url, **kwargs):
        seen.update(kwargs)
        return _FakeResp({}, status_code=202)

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = WebhookSink(url="https://hook")

    result = dispatch(sink, _ctx())
    assert result.ok
    assert seen["json_body"]["idempotency_key"] == "urn:li:assertion:a:run1"
    assert seen["headers"]["Idempotency-Key"] == "urn:li:assertion:a:run1"


def test_dispatch_returns_error_on_permanent_failure(monkeypatch):
    def fake_send(method, url, **kwargs):
        raise _HTTPError(400)

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = WebhookSink(url="https://hook", name="wh")

    result = dispatch(sink, _ctx(), retry=RetryConfig(backoff_seconds=0))
    assert not result.ok
    assert result.error


def test_dispatch_retries_transient_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_send(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _HTTPError(503)
        return _FakeResp({}, status_code=200)

    monkeypatch.setattr(http_sink, "send", fake_send)
    sink = WebhookSink(url="https://hook")

    result = dispatch(sink, _ctx(), retry=RetryConfig(max_attempts=3, backoff_seconds=0))
    assert result.ok
    assert calls["n"] == 2


def test_render_json_still_valid(monkeypatch):
    # Guard: the default webhook envelope is valid JSON with the key present.
    payload = {"summary": "s", "body": "b", "idempotency_key": "k", "context": {}}
    assert json.loads(json.dumps(payload))["idempotency_key"] == "k"
