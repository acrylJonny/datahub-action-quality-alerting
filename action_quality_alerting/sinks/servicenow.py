import logging

from action_quality_alerting.config import ServiceNowSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http

logger = logging.getLogger(__name__)


def send(config: ServiceNowSink, *, summary: str, body: str, dry_run: bool) -> DispatchResult:
    label = config.name or "servicenow"

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would create ServiceNow {config.table}: {summary}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    base = config.base_url.rstrip("/")
    resp = http.send(
        "POST",
        f"{base}/api/now/table/{config.table}",
        headers={"Accept": "application/json"},
        json_body={"short_description": summary, "description": body},
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    result = data.get("result", {}) if isinstance(data, dict) else {}
    number = result.get("number") or result.get("sys_id") or ""
    return DispatchResult(sink=label, ok=True, detail=number)
