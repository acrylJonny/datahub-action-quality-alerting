"""Internal data models: the parsed run outcome, the enriched alert context that
templates render against, and the per-sink dispatch result."""

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AssertionRunOutcome(BaseModel):
    """The fields we care about from an ``assertionRunEvent`` aspect payload."""

    assertion_urn: str | None = None
    assertee_urn: str | None = None  # the dataset the assertion runs on
    status: str | None = None
    result_type: str | None = None
    severity: str | None = None
    run_id: str | None = None
    timestamp_millis: int | None = None
    row_count: int | None = None
    unexpected_count: int | None = None
    missing_count: int | None = None
    actual_agg_value: float | None = None
    external_url: str | None = None
    executed_query: str | None = None

    @classmethod
    def from_aspect(cls, payload: dict[str, Any]) -> "AssertionRunOutcome":
        result = payload.get("result") or {}
        return cls(
            assertion_urn=payload.get("assertionUrn"),
            assertee_urn=payload.get("asserteeUrn"),
            status=payload.get("status"),
            result_type=result.get("type"),
            severity=result.get("severity"),
            run_id=payload.get("runId"),
            timestamp_millis=payload.get("timestampMillis"),
            row_count=result.get("rowCount"),
            unexpected_count=result.get("unexpectedCount"),
            missing_count=result.get("missingCount"),
            actual_agg_value=result.get("actualAggValue"),
            external_url=result.get("externalUrl"),
            executed_query=payload.get("executedQuery"),
        )


def parse_mcl_aspect(raw: bytes | str | None) -> dict[str, Any] | None:
    """Best-effort JSON decode of an MCL GenericAspect value. Timeseries aspects
    are emitted as JSON; a non-JSON payload degrades to None rather than raising."""
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


class AlertContext(BaseModel):
    """Everything a template can reference. Rendered via ``str.format(**vars)``."""

    trigger: str = "assertion run"
    result_type: str = ""
    severity: str = ""
    assertion_urn: str = ""
    assertion_type: str = ""
    assertion_description: str = ""
    asset_urn: str = ""
    asset_name: str = ""
    platform: str = ""
    domain_urn: str = ""
    domain_name: str = ""
    contract_urn: str = ""
    owners: str = ""
    owner_emails: list[str] = Field(default_factory=list)
    row_count: str = ""
    unexpected_count: str = ""
    missing_count: str = ""
    actual_value: str = ""
    external_url: str = ""
    executed_query: str = ""
    run_id: str = ""
    run_time: str = ""
    run_timestamp_millis: int = 0
    datahub_url: str = ""
    # Stable per-failure identity ({assertion_urn}:{run_id|timestamp}); used for
    # sink-level idempotency so replays/retries never create duplicate tickets.
    idempotency_key: str = ""

    def template_vars(self) -> dict[str, str]:
        # A missing placeholder is rendered as an empty string, never a KeyError.
        out: dict[str, str] = {}
        for key, value in self.model_dump().items():
            if isinstance(value, list):
                out[key] = ", ".join(str(v) for v in value)
            else:
                out[key] = "" if value is None else str(value)
        return out


def epoch_millis_to_iso(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


class DispatchResult(BaseModel):
    sink: str
    ok: bool
    detail: str | None = None
    error: str | None = None
