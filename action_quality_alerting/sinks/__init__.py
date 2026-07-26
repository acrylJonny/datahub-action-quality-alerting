"""Sink dispatch: resolve templates, retry transient failures, and route a
rendered alert to the right outbound integration."""

import logging

from action_quality_alerting.config import (
    ChatSink,
    JiraSink,
    RestSink,
    RetryConfig,
    ServiceNowSink,
    SinkConfig,
    WebhookSink,
)
from action_quality_alerting.constants import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_SUMMARY_TEMPLATE,
)
from action_quality_alerting.models import AlertContext, DispatchResult
from action_quality_alerting.retry import retry_call
from action_quality_alerting.sinks import chat, jira, rest, servicenow, webhook
from action_quality_alerting.templating import render

logger = logging.getLogger(__name__)


def _sink_label(sink: SinkConfig) -> str:
    return sink.name or sink.type


def dispatch(
    sink: SinkConfig,
    context: AlertContext,
    *,
    retry: RetryConfig | None = None,
    force_dry_run: bool = False,
) -> DispatchResult:
    retry = retry or RetryConfig()
    variables = context.template_vars()
    summary = render(sink.summary_template or DEFAULT_SUMMARY_TEMPLATE, variables)
    body = render(sink.body_template or DEFAULT_BODY_TEMPLATE, variables)
    dry_run = force_dry_run or sink.dry_run
    key = context.idempotency_key
    label = _sink_label(sink)

    def _send() -> DispatchResult:
        if isinstance(sink, WebhookSink):
            return webhook.send(
                sink,
                summary=summary,
                body=body,
                variables=variables,
                idempotency_key=key,
                dry_run=dry_run,
            )
        if isinstance(sink, RestSink):
            return rest.send(
                sink,
                summary=summary,
                body=body,
                variables=variables,
                idempotency_key=key,
                dry_run=dry_run,
            )
        if isinstance(sink, JiraSink):
            return jira.send(sink, summary=summary, body=body, idempotency_key=key, dry_run=dry_run)
        if isinstance(sink, ServiceNowSink):
            return servicenow.send(
                sink, summary=summary, body=body, idempotency_key=key, dry_run=dry_run
            )
        if isinstance(sink, ChatSink):
            return chat.send(sink, summary=summary, body=body, dry_run=dry_run)
        raise ValueError(f"unknown sink type {sink.type!r}")

    try:
        return retry_call(_send, retry=retry, label=label)
    except Exception as exc:
        logger.error(f"[sink:{label}] permanently failed after retries: {exc}")
        return DispatchResult(sink=label, ok=False, error=str(exc))
