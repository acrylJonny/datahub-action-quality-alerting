"""Turn a parsed run outcome into a rich AlertContext (for templates) plus the
flat MatchFacts a rule filter evaluates against."""

import logging

from pydantic import BaseModel, Field

from action_quality_alerting import graphql as gql
from action_quality_alerting.models import (
    AlertContext,
    AssertionRunOutcome,
    epoch_millis_to_iso,
)

logger = logging.getLogger(__name__)


class MatchFacts(BaseModel):
    result_type: str | None = None
    severity: str | None = None
    assertion_type: str | None = None
    asset_urn: str | None = None
    platform_key: str | None = None  # normalised, e.g. "databricks"
    domain_urn: str | None = None
    domain_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_contract_assertion: bool = False
    contract_urn: str | None = None


class EnrichedAlert(BaseModel):
    context: AlertContext
    facts: MatchFacts
    assertion_urn: str | None = None
    run_timestamp_millis: int = 0
    # The assertion GraphQL payload used for enrichment; reused for dedup so we do
    # not fetch it twice.
    assertion: dict = Field(default_factory=dict)


def _dataset_tags(dataset: dict) -> list[str]:
    tags: list[str] = []
    for item in (dataset.get("tags") or {}).get("tags") or []:
        tag = (item or {}).get("tag") or {}
        if tag.get("urn"):
            tags.append(tag["urn"])
    return tags


def build_alert(
    graph: object,
    outcome: AssertionRunOutcome,
    *,
    assertion: dict | None = None,
    datahub_base_url: str = "",
) -> EnrichedAlert:
    if assertion is None:
        assertion = (
            gql.assertion_details(graph, outcome.assertion_urn) if outcome.assertion_urn else {}
        )

    dataset_urn = outcome.assertee_urn or gql.dataset_from_assertion(assertion)
    dataset = gql.enrich_dataset(graph, dataset_urn) if dataset_urn else {}

    domain_urn, domain_name = gql.domain_ref(dataset)
    platform = gql.platform_name(dataset)
    contract_urn, bound_assertions = gql.contract_urn_and_assertions(dataset)
    is_contract = bool(outcome.assertion_urn and outcome.assertion_urn in bound_assertions)

    asset_name = (
        (dataset.get("properties") or {}).get("qualifiedName")
        or (dataset.get("properties") or {}).get("name")
        or dataset.get("name")
        or dataset_urn
        or ""
    )

    context = AlertContext(
        trigger="data contract validation" if is_contract else "assertion run",
        result_type=outcome.result_type or "",
        severity=outcome.severity or "",
        assertion_urn=outcome.assertion_urn or "",
        assertion_type=gql.assertion_type(assertion) or "",
        assertion_description=gql.assertion_description(assertion) or "",
        asset_urn=dataset_urn or "",
        asset_name=asset_name,
        platform=platform or "",
        domain_urn=domain_urn or "",
        domain_name=domain_name or "",
        contract_urn=contract_urn or "",
        owners=", ".join(gql.owner_labels(dataset)),
        owner_emails=gql.owner_emails(dataset),
        row_count="" if outcome.row_count is None else str(outcome.row_count),
        unexpected_count="" if outcome.unexpected_count is None else str(outcome.unexpected_count),
        missing_count="" if outcome.missing_count is None else str(outcome.missing_count),
        actual_value="" if outcome.actual_agg_value is None else str(outcome.actual_agg_value),
        external_url=outcome.external_url or "",
        executed_query=outcome.executed_query or "",
        run_id=outcome.run_id or "",
        run_time=epoch_millis_to_iso(outcome.timestamp_millis),
        run_timestamp_millis=outcome.timestamp_millis or 0,
        datahub_url=_asset_url(datahub_base_url, dataset_urn),
    )

    facts = MatchFacts(
        result_type=outcome.result_type,
        severity=outcome.severity,
        assertion_type=context.assertion_type or None,
        asset_urn=dataset_urn,
        platform_key=_platform_key(dataset),
        domain_urn=domain_urn,
        domain_name=domain_name,
        tags=_dataset_tags(dataset),
        is_contract_assertion=is_contract,
        contract_urn=contract_urn,
    )

    return EnrichedAlert(
        context=context,
        facts=facts,
        assertion_urn=outcome.assertion_urn,
        run_timestamp_millis=outcome.timestamp_millis or 0,
        assertion=assertion,
    )


def _platform_key(dataset: dict) -> str | None:
    # The raw platform name from the URN segment (e.g. "databricks"), not the
    # display name — filters match against this.
    platform = dataset.get("platform") or {}
    name = platform.get("name")
    if not name:
        return None
    # platform.name is already the short key in GraphQL (e.g. "databricks").
    return name.lower()


def _asset_url(base_url: str, dataset_urn: str | None) -> str:
    if not base_url or not dataset_urn:
        return ""
    return f"{base_url.rstrip('/')}/dataset/{dataset_urn}"
