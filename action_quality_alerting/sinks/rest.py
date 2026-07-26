import json
import logging

from action_quality_alerting.config import RestSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http
from action_quality_alerting.templating import render

logger = logging.getLogger(__name__)


def send(
    config: RestSink,
    *,
    summary: str,
    body: str,
    variables: dict[str, str],
    dry_run: bool,
) -> DispatchResult:
    label = config.name or "rest"

    if config.body_template:
        rendered = render(config.body_template, variables)
    else:
        rendered = json.dumps({"summary": summary, "body": body, "context": variables})

    headers = dict(config.headers)
    headers.setdefault("Content-Type", config.content_type)

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would {config.method} {config.url}: {rendered}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    resp = http.send(
        config.method,
        config.url,
        headers=headers,
        data=rendered,
        auth=config.auth,
        timeout=config.timeout_seconds,
    )
    return DispatchResult(sink=label, ok=True, detail=f"HTTP {resp.status_code}")
