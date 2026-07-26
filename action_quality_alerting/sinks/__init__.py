"""Sink dispatch: resolve templates and route a rendered alert to the right
outbound integration."""

import logging

from action_quality_alerting.config import (
    ChatSink,
    JiraSink,
    RestSink,
    ServiceNowSink,
    SinkConfig,
    WebhookSink,
)
from action_quality_alerting.constants import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_SUMMARY_TEMPLATE,
)
from action_quality_alerting.models import AlertContext, DispatchResult
from action_quality_alerting.sinks import chat, jira, rest, servicenow, webhook
from action_quality_alerting.templating import render

logger = logging.getLogger(__name__)


def _sink_label(sink: SinkConfig) -> str:
    return sink.name or sink.type


def dispatch(
    sink: SinkConfig, context: AlertContext, *, force_dry_run: bool = False
) -> DispatchResult:
    variables = context.template_vars()
    summary = render(sink.summary_template or DEFAULT_SUMMARY_TEMPLATE, variables)
    body = render(sink.body_template or DEFAULT_BODY_TEMPLATE, variables)
    dry_run = force_dry_run or sink.dry_run
    label = _sink_label(sink)

    try:
        if isinstance(sink, WebhookSink):
            return webhook.send(
                sink, summary=summary, body=body, variables=variables, dry_run=dry_run
            )
        if isinstance(sink, RestSink):
            return rest.send(sink, summary=summary, body=body, variables=variables, dry_run=dry_run)
        if isinstance(sink, JiraSink):
            return jira.send(sink, summary=summary, body=body, dry_run=dry_run)
        if isinstance(sink, ServiceNowSink):
            return servicenow.send(sink, summary=summary, body=body, dry_run=dry_run)
        if isinstance(sink, ChatSink):
            return chat.send(sink, summary=summary, body=body, dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[sink:{label}] dispatch failed: {exc}", exc_info=True)
        return DispatchResult(sink=label, ok=False, error=str(exc))

    return DispatchResult(sink=label, ok=False, error=f"unknown sink type {sink.type!r}")
