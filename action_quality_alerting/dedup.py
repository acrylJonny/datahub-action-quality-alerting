"""DataHub-side deduplication so a scheduled action with catchup does not fire
twice for the same failure.

Two independent layers, both needing no external store:

1. **Transition** (default) — only fire when the *previous* completed run was not
   already a failure, so a persistently-failing check does not open a ticket on
   every run.
2. **Structured-property marker** (optional) — persist the last-handled run
   timestamp on the assertion so a restart/catchup never re-fires a handled run.
   Requires the property to be registered once (scripts/setup_dedup_property.py).
"""

import logging

from action_quality_alerting import graphql as gql
from action_quality_alerting.config import DedupSettings
from action_quality_alerting.constants import (
    GET_ASSERTION_MARKER_QUERY,
    RESULT_ERROR,
    RESULT_FAILURE,
    UPSERT_MARKER_MUTATION,
)

logger = logging.getLogger(__name__)

_FAILING_RESULTS = {RESULT_FAILURE, RESULT_ERROR}

# The marker is on by default; if the structured property is not registered every
# call would otherwise warn. Warn once, then drop to debug so logs stay readable.
_marker_warned = False


def _warn_marker_once(message: str) -> None:
    global _marker_warned
    if _marker_warned:
        logger.debug(message)
        return
    _marker_warned = True
    logger.warning(
        message + " (further marker warnings suppressed; register the property via "
        "scripts/setup_dedup_property.py or set dedup.use_structured_property=false)"
    )


def _property_urn(qualified_name: str) -> str:
    return f"urn:li:structuredProperty:{qualified_name}"


def is_new_failure(assertion: dict, current_ts: int) -> bool:
    """True when the completed run immediately before the current one was not a
    failure (i.e. this is a SUCCESS/ERROR->FAILURE transition, or the first run)."""
    runs = gql.latest_two_run_results(assertion)
    # runEvents are newest-first; index 0 is the current run.
    previous = runs[1] if len(runs) >= 2 else None
    if previous is None:
        return True
    prev_type = (previous.get("result") or {}).get("type")
    return prev_type not in _FAILING_RESULTS


def read_marker(graph: object, assertion_urn: str, qualified_name: str) -> int | None:
    try:
        data = gql.execute_graphql(graph, GET_ASSERTION_MARKER_QUERY, {"urn": assertion_urn})
    except Exception as exc:
        _warn_marker_once(f"[dedup] marker read failed for {assertion_urn}: {exc}")
        return None
    assertion = (data or {}).get("assertion") or {}
    props = (assertion.get("structuredProperties") or {}).get("properties") or []
    target = _property_urn(qualified_name)
    for prop in props:
        sp = (prop or {}).get("structuredProperty") or {}
        if sp.get("urn") != target:
            continue
        for value in prop.get("values") or []:
            number = value.get("numberValue")
            if number is not None:
                return int(number)
            string = value.get("stringValue")
            if string is not None:
                try:
                    return int(float(string))
                except ValueError:
                    return None
    return None


def write_marker(graph: object, assertion_urn: str, qualified_name: str, ts: int) -> None:
    variables = {
        "input": {
            "assetUrn": assertion_urn,
            "structuredPropertyInputParams": [
                {
                    "structuredPropertyUrn": _property_urn(qualified_name),
                    "values": [{"numberValue": ts}],
                }
            ],
        }
    }
    try:
        gql.execute_graphql(graph, UPSERT_MARKER_MUTATION, variables)
    except Exception as exc:
        # A missing/unregistered property must not break alerting; it just means
        # dedup falls back to the transition + in-memory layers.
        _warn_marker_once(f"[dedup] marker write failed for {assertion_urn}: {exc}")


def should_fire(
    graph: object,
    *,
    settings: DedupSettings,
    assertion: dict,
    assertion_urn: str | None,
    run_ts: int,
    seen: set[tuple],
    seen_key: tuple,
) -> bool:
    if seen_key in seen:
        return False

    if settings.only_on_transition and not is_new_failure(assertion, run_ts):
        logger.debug(f"[dedup] {assertion_urn} run {run_ts} is not a new failure — skipping")
        return False

    if settings.use_structured_property and assertion_urn:
        last = read_marker(graph, assertion_urn, settings.property_qualified_name)
        if last is not None and run_ts <= last:
            logger.debug(f"[dedup] {assertion_urn} run {run_ts} <= marker {last} — skipping")
            return False

    return True


def record_fired(
    graph: object,
    *,
    settings: DedupSettings,
    assertion_urn: str | None,
    run_ts: int,
    seen: set[tuple],
    seen_key: tuple,
) -> None:
    seen.add(seen_key)
    if settings.use_structured_property and assertion_urn:
        write_marker(graph, assertion_urn, settings.property_qualified_name, run_ts)
