import logging

from action_quality_alerting.config import ChatPlatform, ChatSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http

logger = logging.getLogger(__name__)


def _payload(platform: ChatPlatform, summary: str, body: str) -> dict[str, str]:
    # Both Slack and Teams incoming webhooks accept a simple {"text": ...} body.
    if platform == ChatPlatform.SLACK:
        return {"text": f"*{summary}*\n{body}"}
    return {"text": f"{summary}\n\n{body}"}


def send(config: ChatSink, *, summary: str, body: str, dry_run: bool) -> DispatchResult:
    label = config.name or f"chat:{config.platform.value}"

    if dry_run:
        logger.info(f"[DRY RUN][{label}] would post to {config.platform.value} webhook: {summary}")
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    resp = http.send(
        "POST",
        config.webhook_url,
        json_body=_payload(config.platform, summary, body),
        timeout=config.timeout_seconds,
    )
    return DispatchResult(sink=label, ok=True, detail=f"HTTP {resp.status_code}")
