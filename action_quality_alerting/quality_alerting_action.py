import logging

from datahub_actions.action.action import Action
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.event.event_registry import MetadataChangeLogEvent
from datahub_actions.pipeline.pipeline_context import PipelineContext

from action_quality_alerting import dedup
from action_quality_alerting.config import QualityAlertingConfig, RuleConfig
from action_quality_alerting.constants import (
    ASSERTION_ENTITY,
    ASSERTION_RUN_EVENT_ASPECT,
    MCL_EVENT_TYPE,
    RESULT_FAILURE,
    RUN_STATUS_COMPLETE,
)
from action_quality_alerting.enrich import EnrichedAlert, build_alert
from action_quality_alerting.graphql import (
    assertion_details,
    dataset_from_assertion,
    latest_two_run_results,
    search_failed_assertions,
)
from action_quality_alerting.matcher import matches
from action_quality_alerting.models import AssertionRunOutcome, parse_mcl_aspect
from action_quality_alerting.sinks import dispatch

logger = logging.getLogger(__name__)


class QualityAlertingAction(Action):
    """Trigger external actions (webhook / REST / Jira / ServiceNow / chat) in
    response to DataHub assertion & data-contract validation results."""

    def __init__(self, config: QualityAlertingConfig, ctx: PipelineContext) -> None:
        self.config = config
        self.ctx = ctx
        # (rule_name, assertion_urn, run_ts) tuples already handled this process.
        self._seen: set[tuple] = set()
        logger.info(
            f"[QualityAlerting] Initialised with {len(config.rules)} rule(s)"
            + (" [GLOBAL DRY RUN]" if config.dry_run else "")
        )

    @classmethod
    def create(cls, config_dict: dict, ctx: PipelineContext) -> "Action":
        config = QualityAlertingConfig.model_validate(config_dict or {})
        action = cls(config, ctx)
        action._startup_catchup()
        return action

    # ------------------------------------------------------------------ #
    # Catchup                                                            #
    # ------------------------------------------------------------------ #

    def _startup_catchup(self) -> None:
        result_types = self._all_result_types()
        if not result_types:
            return
        logger.info(f"[Catchup] Scanning for assertions with latest result in {result_types}")
        try:
            urns = search_failed_assertions(self.ctx.graph, result_types)
        except Exception as exc:
            logger.error(f"[Catchup] Search failed: {exc}", exc_info=True)
            return
        logger.info(f"[Catchup] {len(urns)} candidate assertion(s)")
        for assertion_urn in urns:
            try:
                self._process_from_history(assertion_urn)
            except Exception as exc:
                logger.error(f"[Catchup] Error processing {assertion_urn}: {exc}", exc_info=True)

    def _process_from_history(self, assertion_urn: str) -> None:
        assertion = assertion_details(self.ctx.graph, assertion_urn)
        runs = latest_two_run_results(assertion)
        if not runs:
            return
        newest = runs[0]
        result_type = (newest.get("result") or {}).get("type")
        outcome = AssertionRunOutcome(
            assertion_urn=assertion_urn,
            assertee_urn=dataset_from_assertion(assertion),
            status=RUN_STATUS_COMPLETE,
            result_type=result_type,
            timestamp_millis=newest.get("timestampMillis"),
        )
        self._process(outcome, assertion=assertion)

    # ------------------------------------------------------------------ #
    # Live events                                                        #
    # ------------------------------------------------------------------ #

    def act(self, event: EventEnvelope) -> None:
        if event.event_type != MCL_EVENT_TYPE:
            return
        mcl: MetadataChangeLogEvent = event.event
        if getattr(mcl, "entityType", None) != ASSERTION_ENTITY:
            return
        if getattr(mcl, "aspectName", None) != ASSERTION_RUN_EVENT_ASPECT:
            return

        assertion_urn = getattr(mcl, "entityUrn", None)
        aspect = getattr(mcl, "aspect", None)
        payload = parse_mcl_aspect(getattr(aspect, "value", None)) if aspect else None

        if payload is None:
            # Aspect body not available/parseable — fall back to a fresh GraphQL read.
            if assertion_urn:
                self._process_from_history(assertion_urn)
            return

        outcome = AssertionRunOutcome.from_aspect(payload)
        if not outcome.assertion_urn:
            outcome.assertion_urn = assertion_urn
        if outcome.status and outcome.status != RUN_STATUS_COMPLETE:
            return
        self._process(outcome)

    # ------------------------------------------------------------------ #
    # Core                                                               #
    # ------------------------------------------------------------------ #

    def _process(self, outcome: AssertionRunOutcome, assertion: dict | None = None) -> None:
        applicable = [r for r in self.config.rules if outcome.result_type in r.match.result_types]
        if not applicable:
            return

        alert: EnrichedAlert = build_alert(
            self.ctx.graph,
            outcome,
            assertion=assertion,
            datahub_base_url=self.config.datahub_base_url or "",
        )

        for rule in applicable:
            if not matches(rule.match, alert.facts):
                continue
            self._fire_rule(rule, alert)

    def _fire_rule(self, rule: RuleConfig, alert: EnrichedAlert) -> None:
        settings = self.config.dedup_for(rule)
        seen_key = (rule.name, alert.assertion_urn or "", alert.run_timestamp_millis)

        should = dedup.should_fire(
            self.ctx.graph,
            settings=settings,
            assertion=alert.assertion,
            assertion_urn=alert.assertion_urn,
            run_ts=alert.run_timestamp_millis,
            seen=self._seen,
            seen_key=seen_key,
        )
        if not should:
            return

        logger.info(
            f"[Rule:{rule.name}] firing {len(rule.sinks)} sink(s) for "
            f"{alert.facts.result_type} on {alert.context.asset_name}"
        )
        any_ok = False
        for sink in rule.sinks:
            result = dispatch(sink, alert.context, force_dry_run=self.config.dry_run)
            if result.ok:
                any_ok = True
                logger.info(f"[Rule:{rule.name}] sink {result.sink}: {result.detail}")
            else:
                logger.error(f"[Rule:{rule.name}] sink {result.sink} failed: {result.error}")

        if any_ok:
            dedup.record_fired(
                self.ctx.graph,
                settings=settings,
                assertion_urn=alert.assertion_urn,
                run_ts=alert.run_timestamp_millis,
                seen=self._seen,
                seen_key=seen_key,
            )

    def _all_result_types(self) -> list[str]:
        types: set[str] = set()
        for rule in self.config.rules:
            types.update(rule.match.result_types or [RESULT_FAILURE])
        return sorted(types)

    def close(self) -> None:
        logger.info("[QualityAlerting] Closed")
