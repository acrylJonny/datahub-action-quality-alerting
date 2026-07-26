"""Thin, defensive GraphQL helpers. Every accessor tolerates a missing field so a
DataHub Cloud version that does not expose something degrades to None rather than
crashing the action."""

import logging
from typing import Any

from action_quality_alerting.constants import (
    ASSERTION_RUN_HISTORY_QUERY,
    ENRICH_DATASET_QUERY,
    SEARCH_FAILED_ASSERTIONS_QUERY,
)

logger = logging.getLogger(__name__)


def execute_graphql(graph: object, query: str, variables: dict[str, Any]) -> Any:
    """Works with both DataHubGraph (execute_graphql directly) and
    AcrylDataHubGraph (which wraps a DataHubGraph in .graph)."""
    if hasattr(graph, "execute_graphql"):
        return graph.execute_graphql(query, variables=variables)  # type: ignore[attr-defined]
    inner = getattr(graph, "graph", None)
    if inner is not None and hasattr(inner, "execute_graphql"):
        return inner.execute_graphql(query, variables=variables)
    raise AttributeError(f"Graph object {type(graph)} has no execute_graphql method")


def _safe(graph: object, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        result = execute_graphql(graph, query, variables)
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.warning(f"GraphQL query failed ({variables}): {exc}")
        return {}


def enrich_dataset(graph: object, dataset_urn: str) -> dict[str, Any]:
    data = _safe(graph, ENRICH_DATASET_QUERY, {"urn": dataset_urn})
    dataset = data.get("dataset")
    return dataset if isinstance(dataset, dict) else {}


def assertion_details(graph: object, assertion_urn: str) -> dict[str, Any]:
    data = _safe(graph, ASSERTION_RUN_HISTORY_QUERY, {"urn": assertion_urn})
    assertion = data.get("assertion")
    return assertion if isinstance(assertion, dict) else {}


def search_failed_assertions(
    graph: object, result_types: list[str], *, batch: int = 200, max_results: int = 2000
) -> list[str]:
    """Assertion URNs whose most recent result is in `result_types`. Used by the
    startup catchup pass to recover failures missed while the action was down."""
    urns: list[str] = []
    start = 0
    while start < max_results:
        data = _safe(
            graph,
            SEARCH_FAILED_ASSERTIONS_QUERY,
            {"start": start, "count": batch, "resultTypes": result_types},
        )
        search = data.get("searchAcrossEntities") or {}
        results = search.get("searchResults") or []
        if not results:
            break
        for row in results:
            entity = (row or {}).get("entity") or {}
            urn = entity.get("urn")
            if urn:
                urns.append(urn)
        total = search.get("total") or 0
        start += batch
        if start >= total:
            break
    return urns


# --------------------------------------------------------------------------- #
# Field extraction helpers                                                     #
# --------------------------------------------------------------------------- #


def latest_two_run_results(assertion: dict[str, Any]) -> list[dict[str, Any]]:
    run_events = (assertion.get("runEvents") or {}).get("runEvents") or []
    return [r for r in run_events if isinstance(r, dict)]


def assertion_type(assertion: dict[str, Any]) -> str | None:
    info = assertion.get("info") or {}
    return info.get("type")


def assertion_description(assertion: dict[str, Any]) -> str | None:
    info = assertion.get("info") or {}
    return info.get("description")


def dataset_from_assertion(assertion: dict[str, Any]) -> str | None:
    info = assertion.get("info") or {}
    ds = info.get("datasetAssertion") or {}
    return ds.get("datasetUrn")


def owner_emails(dataset: dict[str, Any]) -> list[str]:
    emails: list[str] = []
    for owner in (dataset.get("ownership") or {}).get("owners") or []:
        props = ((owner or {}).get("owner") or {}).get("properties") or {}
        email = props.get("email")
        if email:
            emails.append(email)
    return emails


def owner_labels(dataset: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for owner in (dataset.get("ownership") or {}).get("owners") or []:
        entity = (owner or {}).get("owner") or {}
        props = entity.get("properties") or {}
        labels.append(props.get("displayName") or props.get("email") or entity.get("urn") or "")
    return [label for label in labels if label]


def domain_ref(dataset: dict[str, Any]) -> tuple[str | None, str | None]:
    domain = ((dataset.get("domain") or {}).get("domain")) or {}
    name = (domain.get("properties") or {}).get("name")
    return domain.get("urn"), name


def platform_name(dataset: dict[str, Any]) -> str | None:
    platform = dataset.get("platform") or {}
    props = platform.get("properties") or {}
    return props.get("displayName") or platform.get("name")


def contract_urn_and_assertions(dataset: dict[str, Any]) -> tuple[str | None, set[str]]:
    """Return the dataset's Data Contract URN (if any) and the set of assertion
    URNs the contract binds (freshness + schema + dataQuality)."""
    contract = dataset.get("contract") or {}
    contract_urn = contract.get("urn")
    props = contract.get("properties") or {}
    bound: set[str] = set()
    for section in ("freshness", "schema", "dataQuality"):
        for item in props.get(section) or []:
            assertion = (item or {}).get("assertion") or {}
            urn = assertion.get("urn")
            if urn:
                bound.add(urn)
    return contract_urn, bound
