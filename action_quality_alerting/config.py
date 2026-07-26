"""Pydantic configuration for the Quality Alerting action.

A deployment is a list of ``rules``. Each rule has a ``match`` (which events fire
it) and one or more ``sinks`` (the external actions to trigger). This keeps a
single action process able to serve many event->action mappings.
"""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from action_quality_alerting.constants import (
    DEDUP_PROPERTY_QUALIFIED_NAME,
    RESULT_FAILURE,
)

# --------------------------------------------------------------------------- #
# HTTP auth (shared by webhook / rest / chat sinks)                           #
# --------------------------------------------------------------------------- #


class HTTPAuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    HMAC = "hmac"


class HTTPAuthConfig(BaseModel):
    type: HTTPAuthType = HTTPAuthType.NONE

    # bearer
    token: str | None = None
    # basic
    username: str | None = None
    password: str | None = None
    # hmac (body is signed; the hex digest is sent in `header`)
    secret: str | None = None
    header: str = "X-Signature"
    algorithm: str = "sha256"

    @model_validator(mode="after")
    def _require_fields(self) -> "HTTPAuthConfig":
        if self.type == HTTPAuthType.BEARER and not self.token:
            raise ValueError("auth.token is required for auth.type=bearer")
        if self.type == HTTPAuthType.BASIC and not (self.username and self.password):
            raise ValueError("auth.username and auth.password are required for auth.type=basic")
        if self.type == HTTPAuthType.HMAC and not self.secret:
            raise ValueError("auth.secret is required for auth.type=hmac")
        return self


# --------------------------------------------------------------------------- #
# Sinks                                                                        #
# --------------------------------------------------------------------------- #


class _SinkBase(BaseModel):
    # A friendly name used in logs / dedup fingerprints.
    name: str | None = None
    # Templates override rule/global defaults. Placeholders are AlertContext keys.
    summary_template: str | None = None
    body_template: str | None = None
    dry_run: bool = False
    timeout_seconds: int = 30


class WebhookSink(_SinkBase):
    type: Literal["webhook"] = "webhook"
    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    auth: HTTPAuthConfig = Field(default_factory=HTTPAuthConfig)
    # Optional raw JSON body template. When omitted a default envelope
    # ({"summary","body","context"}) is sent.
    json_template: str | None = None


class RestSink(_SinkBase):
    type: Literal["rest"] = "rest"
    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    auth: HTTPAuthConfig = Field(default_factory=HTTPAuthConfig)
    # Arbitrary request body template (sent verbatim after rendering).
    body_template: str | None = None
    content_type: str = "application/json"


class JiraSink(_SinkBase):
    type: Literal["jira"] = "jira"
    base_url: str
    username: str
    api_token: str
    project_key: str
    issue_type: str = "Task"


class ServiceNowSink(_SinkBase):
    type: Literal["servicenow"] = "servicenow"
    base_url: str
    username: str
    api_token: str
    table: str = "incident"


class ChatPlatform(str, Enum):
    SLACK = "slack"
    TEAMS = "teams"


class ChatSink(_SinkBase):
    type: Literal["chat"] = "chat"
    platform: ChatPlatform
    webhook_url: str


SinkConfig = Annotated[
    WebhookSink | RestSink | JiraSink | ServiceNowSink | ChatSink,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Match + dedup + rule                                                         #
# --------------------------------------------------------------------------- #


class TriggerEvent(str, Enum):
    # assertionRunEvent COMPLETE with a result type in `result_types`. A data
    # contract failing is expressed here via match.only_contract_assertions,
    # since a contract breach is one of its bound assertions failing.
    ASSERTION_RESULT = "assertion_result"


class MatchFilter(BaseModel):
    """Optional narrowing on the enriched context. All present clauses must hold."""

    domains: list[str] = Field(default_factory=list)  # domain URNs or names
    tags: list[str] = Field(default_factory=list)  # tag URNs
    platforms: list[str] = Field(default_factory=list)  # e.g. ["databricks", "snowflake"]
    asset_urn_regex: str | None = None
    assertion_types: list[str] = Field(default_factory=list)  # e.g. ["FRESHNESS", "VOLUME"]
    severities: list[str] = Field(default_factory=list)  # e.g. ["HIGH"]


class MatchConfig(BaseModel):
    event: TriggerEvent = TriggerEvent.ASSERTION_RESULT
    result_types: list[str] = Field(default_factory=lambda: [RESULT_FAILURE])
    # Only fire for assertions that back a Data Contract (contract validation).
    only_contract_assertions: bool = False
    filter: MatchFilter = Field(default_factory=MatchFilter)


class DedupSettings(BaseModel):
    # Only fire when the previous completed run was not already a failure, so a
    # persistently-failing check does not open a ticket on every scheduled run.
    only_on_transition: bool = True
    # Persist a marker (structured property on the assertion) so restarts /
    # replays never re-fire for a run already handled. On by default for
    # durability; register the property once (scripts/setup_dedup_property.py).
    # If the property is missing, dedup degrades to the transition + sink-level
    # idempotency layers rather than failing.
    use_structured_property: bool = True
    property_qualified_name: str = DEDUP_PROPERTY_QUALIFIED_NAME


class RetryConfig(BaseModel):
    """In-process retry for transient sink failures (5xx / 429 / timeouts /
    connection errors). Non-transient errors (4xx, bad templates) fail fast."""

    max_attempts: int = 4
    backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0


class RuleConfig(BaseModel):
    name: str
    match: MatchConfig = Field(default_factory=MatchConfig)
    sinks: list[SinkConfig]
    dedup: DedupSettings | None = None

    @model_validator(mode="after")
    def _require_sinks(self) -> "RuleConfig":
        if not self.sinks:
            raise ValueError(f"rule {self.name!r} must declare at least one sink")
        return self


class QualityAlertingConfig(BaseModel):
    rules: list[RuleConfig]
    # Base DataHub URL used to build clickable asset links in alerts (optional).
    datahub_base_url: str | None = None
    # How far back to scan for failed runs on each startup catchup pass.
    lookback_days: int = 7
    # Global default dedup, overridable per rule.
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    # In-process retry policy for transient sink failures.
    retry: RetryConfig = Field(default_factory=RetryConfig)
    # Global dry-run forces every sink into dry-run regardless of its own flag.
    dry_run: bool = False

    @model_validator(mode="after")
    def _require_rules(self) -> "QualityAlertingConfig":
        if not self.rules:
            raise ValueError("at least one rule is required")
        return self

    def dedup_for(self, rule: RuleConfig) -> DedupSettings:
        return rule.dedup or self.dedup
