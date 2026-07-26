import logging

from action_quality_alerting.config import ServiceNowSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http

logger = logging.getLogger(__name__)


def _find_existing(config: ServiceNowSink, base: str, correlation_id: str) -> str:
    """Return the number/sys_id of an existing record with this correlation_id, else ''."""
    resp = http.send(
        "GET",
        f"{base}/api/now/table/{config.table}",
        headers={"Accept": "application/json"},
        params={
            "sysparm_query": f"correlation_id={correlation_id}",
            "sysparm_limit": "1",
            "sysparm_fields": "number,sys_id",
        },
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    results = data.get("result", []) if isinstance(data, dict) else []
    if not results:
        return ""
    first = results[0]
    return first.get("number") or first.get("sys_id") or ""


def send(
    config: ServiceNowSink, *, summary: str, body: str, idempotency_key: str, dry_run: bool
) -> DispatchResult:
    label = config.name or "servicenow"

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would create ServiceNow {config.table}: {summary}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    base = config.base_url.rstrip("/")

    if idempotency_key:
        existing = _find_existing(config, base, idempotency_key)
        if existing:
            logger.info(
                f"[{label}] existing record {existing} for {idempotency_key}; skipping create"
            )
            return DispatchResult(sink=label, ok=True, detail=f"existing {existing}")

    payload: dict[str, str] = {"short_description": summary, "description": body}
    if idempotency_key:
        payload["correlation_id"] = idempotency_key

    resp = http.send(
        "POST",
        f"{base}/api/now/table/{config.table}",
        headers={"Accept": "application/json"},
        json_body=payload,
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    result = data.get("result", {}) if isinstance(data, dict) else {}
    number = result.get("number") or result.get("sys_id") or ""
    return DispatchResult(sink=label, ok=True, detail=number)
