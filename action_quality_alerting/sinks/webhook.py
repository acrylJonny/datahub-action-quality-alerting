import logging

from action_quality_alerting.config import WebhookSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http
from action_quality_alerting.templating import render_json

logger = logging.getLogger(__name__)


def send(
    config: WebhookSink,
    *,
    summary: str,
    body: str,
    variables: dict[str, str],
    dry_run: bool,
) -> DispatchResult:
    label = config.name or "webhook"

    if config.json_template:
        payload = render_json(config.json_template, variables)
    else:
        payload = {"summary": summary, "body": body, "context": variables}

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would POST to {config.url}: {payload}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    resp = http.send(
        config.method,
        config.url,
        headers=config.headers,
        json_body=payload,
        auth=config.auth,
        timeout=config.timeout_seconds,
    )
    return DispatchResult(sink=label, ok=True, detail=f"HTTP {resp.status_code}")
