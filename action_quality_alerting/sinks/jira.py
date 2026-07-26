import logging
import re

from action_quality_alerting.config import JiraSink
from action_quality_alerting.models import DispatchResult
from action_quality_alerting.sinks import http

logger = logging.getLogger(__name__)

_LABEL_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_LABEL_PREFIX = "dhq-"


def _dedup_label(idempotency_key: str) -> str:
    # Jira labels cannot contain whitespace; collapse everything else to a stable token.
    return _LABEL_PREFIX + _LABEL_SANITIZE_RE.sub("_", idempotency_key).strip("_")


def _find_existing(config: JiraSink, base: str, label: str) -> str:
    """Return the key of an existing issue carrying this dedup label, else ''.

    This makes create idempotent across replays/retries: a re-delivered failure
    finds the ticket it already opened instead of opening a second one.
    """
    jql = f'project = "{config.project_key}" AND labels = "{label}"'
    resp = http.send(
        "GET",
        f"{base}/rest/api/2/search",
        headers={"Accept": "application/json"},
        params={"jql": jql, "maxResults": "1", "fields": "key"},
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    issues = data.get("issues", []) if isinstance(data, dict) else []
    return issues[0].get("key", "") if issues else ""


def send(
    config: JiraSink, *, summary: str, body: str, idempotency_key: str, dry_run: bool
) -> DispatchResult:
    label = config.name or "jira"
    dedup_label = _dedup_label(idempotency_key) if idempotency_key else ""

    if dry_run:
        logger.info(
            f"[DRY RUN][{label}] would create Jira issue in {config.project_key}: {summary}"
        )
        return DispatchResult(sink=label, ok=True, detail="dry-run")

    base = config.base_url.rstrip("/")

    if dedup_label:
        existing = _find_existing(config, base, dedup_label)
        if existing:
            existing_url = f"{base}/browse/{existing}"
            logger.info(
                f"[{label}] existing issue {existing} for {idempotency_key}; skipping create"
            )
            return DispatchResult(
                sink=label, ok=True, detail=f"existing {existing} ({existing_url})"
            )

    fields: dict[str, object] = {
        "project": {"key": config.project_key},
        "summary": summary,
        "description": body,
        "issuetype": {"name": config.issue_type},
    }
    if dedup_label:
        fields["labels"] = [dedup_label]

    resp = http.send(
        "POST",
        f"{base}/rest/api/2/issue",
        headers={"Accept": "application/json"},
        json_body={"fields": fields},
        basic_auth=(config.username, config.api_token),
        timeout=config.timeout_seconds,
    )
    data = resp.json() if resp.content else {}
    key = data.get("key", "")
    url = f"{base}/browse/{key}" if key else None
    return DispatchResult(sink=label, ok=True, detail=f"{key} ({url})" if url else key)
