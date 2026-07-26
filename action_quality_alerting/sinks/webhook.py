import logging

from action_quality_alerting.config import WebhookSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http
from action_quality_alerting.templating import render_json

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"


def send(
    config: WebhookSink,
    *,
    summary: str,
    body: str,
    variables: dict[str, str],
    idempotency_key: str,
    dry_run: bool,
) -> DispatchResult:
    label = config.name or "webhook"

    if config.json_template:
        payload = render_json(config.json_template, variables)
    else:
        payload = {
            "summary": summary,
            "body": body,
            "idempotency_key": idempotency_key,
            "context": variables,
        }

    # The receiver can dedupe on this header even for custom json_template bodies.
    headers = dict(config.headers)
    if idempotency_key:
        headers.setdefault(IDEMPOTENCY_HEADER, idempotency_key)

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would POST to {config.url}: {payload}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    resp = http.send(
        config.method,
        config.url,
        headers=headers,
        json_body=payload,
        auth=config.auth,
        timeout=config.timeout_seconds,
    )
    return DispatchResult(sink=label, ok=True, detail=f"HTTP {resp.status_code}")
