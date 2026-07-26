import logging

from action_quality_alerting.config import JiraSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http

logger = logging.getLogger(__name__)


def send(config: JiraSink, *, summary: str, body: str, dry_run: bool) -> DispatchResult:
    label = config.name or "jira"

    if dry_run:
        logger.info(
            f"[DRY RUN][{label}] would create Jira issue in {config.project_key}: {summary}"
        )
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    base = config.base_url.rstrip("/")
    payload = {
        "fields": {
            "project": {"key": config.project_key},
            "summary": summary,
            "description": body,
            "issuetype": {"name": config.issue_type},
        }
    }
    resp = http.send(
        "POST",
        f"{base}/rest/api/2/issue",
        headers={"Accept": "application/json"},
        json_body=payload,
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    key = data.get("key", "")
    url = f"{base}/browse/{key}" if key else None
    return DispatchResult(sink=label, ok=True, detail=f"{key} ({url})" if url else key)
