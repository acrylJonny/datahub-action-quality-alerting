from action_quality_alerting.config import (
    HTTPAuthConfig,
    HTTPAuthType,
    JiraSink,
    WebhookSink,
)
from action_quality_alerting.models import AlertContext
from action_quality_alerting.sinks import dispatch
from action_quality_alerting.sinks import http as http_sink


def _ctx() -> AlertContext:
    return AlertContext(
        result_type="FAILURE", asset_name="cat.sch.tbl", asset_urn="urn:li:dataset:x"
    )


def test_dispatch_jira_dry_run_uses_templates():
    sink = JiraSink(
        base_url="https://x.atlassian.net",
        username="u",
        api_token="t",
        project_key="DQ",
        dry_run=True,
        summary_template="fail: {asset_name}",
    )
    result = dispatch(sink, _ctx())
    assert result.ok
    assert result.detail == "dry-run"


def test_dispatch_webhook_force_dry_run():
    sink = WebhookSink(url="https://h", name="wh")
    result = dispatch(sink, _ctx(), force_dry_run=True)
    assert result.ok
    assert result.sink == "wh"


def test_hmac_signature_is_deterministic():
    auth = HTTPAuthConfig(type=HTTPAuthType.HMAC, secret="s")
    sig1 = http_sink._sign(auth.secret, auth.algorithm, b"body")
    sig2 = http_sink._sign(auth.secret, auth.algorithm, b"body")
    assert sig1 == sig2
    assert sig1 != http_sink._sign(auth.secret, auth.algorithm, b"other")
