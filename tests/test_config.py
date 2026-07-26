import pytest
from pydantic import ValidationError

from action_quality_alerting.config import (
    JiraSink,
    QualityAlertingConfig,
    WebhookSink,
)


def _cfg(**overrides) -> dict:
    base = {
        "rules": [
            {
                "name": "r1",
                "match": {"result_types": ["FAILURE"], "only_contract_assertions": True},
                "sinks": [
                    {
                        "type": "jira",
                        "base_url": "https://x.atlassian.net",
                        "username": "u",
                        "api_token": "t",
                        "project_key": "DQ",
                    }
                ],
            }
        ]
    }
    base.update(overrides)
    return base


def test_parses_and_discriminates_sink_type():
    cfg = QualityAlertingConfig.model_validate(_cfg())
    sink = cfg.rules[0].sinks[0]
    assert isinstance(sink, JiraSink)
    assert cfg.rules[0].match.only_contract_assertions is True


def test_webhook_discriminated():
    cfg = QualityAlertingConfig.model_validate(
        _cfg(
            rules=[
                {
                    "name": "w",
                    "sinks": [{"type": "webhook", "url": "https://h"}],
                }
            ]
        )
    )
    assert isinstance(cfg.rules[0].sinks[0], WebhookSink)


def test_requires_at_least_one_rule():
    with pytest.raises(ValidationError):
        QualityAlertingConfig.model_validate({"rules": []})


def test_rule_requires_a_sink():
    with pytest.raises(ValidationError):
        QualityAlertingConfig.model_validate({"rules": [{"name": "x", "sinks": []}]})


def test_bearer_auth_requires_token():
    with pytest.raises(ValidationError):
        WebhookSink.model_validate(
            {"type": "webhook", "url": "https://h", "auth": {"type": "bearer"}}
        )


def test_rule_dedup_overrides_global():
    cfg = QualityAlertingConfig.model_validate(_cfg(dedup={"only_on_transition": False}))
    # rule has no dedup -> inherits global
    assert cfg.dedup_for(cfg.rules[0]).only_on_transition is False
