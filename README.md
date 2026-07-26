# datahub-action-quality-alerting

A [DataHub Actions](https://docs.datahub.com/docs/actions) handler that triggers
**external actions** when a DataHub **assertion / data-contract validation**
produces a result you care about — for example, **open a Jira ticket when a data
contract fails**, instead of only sending a Slack/Teams/email notification.

It follows the same pattern as
[datahub-action-access-provisioner](https://github.com/acrylJonny/datahub-action-access-provisioner):
an Action that listens for DataHub events and calls out to external systems, with
a startup-catchup + scheduled model suited to the DataHub Cloud remote executor.

## Why this exists (what's native vs. the gap)

On assertion/contract failure DataHub Cloud already gives you:

- **Subscriptions** → Slack / Teams / email notifications.
- **Assertion Actions** → auto-raise/resolve **incidents**.

What is **not** native — and what this action adds — is **arbitrary outbound
actions**: create a Jira/ServiceNow ticket, POST to a webhook, or call any
external REST API when a check fails.

> This is a **DataHub Action**, not a native _Action Workflow_. Action Workflows
> are form-driven, human-approval processes triggered only by `FORM_SUBMITTED` —
> they cannot be triggered by a validation failure. Event reactions belong in the
> Actions framework, which is exactly what this repo is.

## How it works

```
Assertion/contract runs  ─▶  MetadataChangeLogEvent (entityType=assertion,
                                                     aspect=assertionRunEvent)
                              │
                              ▼  QualityAlertingAction.act()
      parse result (SUCCESS/FAILURE/ERROR) ─▶ enrich via GraphQL
        (asset, owners, domain, contract, run details)
          ─▶ match rules ─▶ dedup ─▶ retry+dispatch to sinks
                                       (webhook | rest | jira | servicenow | chat)

First-run backfill (one-shot, via `stage: bootstrap`):
      search assertions whose latest result is FAILURE ─▶ same pipeline
```

Run this as a **live, always-on** action. Down-then-up catch-up is automatic: the
DataHub Cloud remote source persists a durable consumer offset (keyed by the
action URN), so events produced while the action was down are **replayed** on
restart — you do not need a periodic re-scan. For the very first deployment (no
saved offset) or a full historical backfill, run the action once with
`stage: bootstrap`, or configure `lookback_days` on the event source.

## Rules and sinks

A deployment is a list of **rules**. Each rule has a **match** (which events fire
it) and one or more **sinks** (the external actions). One action process can serve
many event→action mappings.

### Match

| Key | Purpose |
| --- | ------- |
| `event` | `assertion_result` (assertion run completed). A contract breach is one of its bound assertions failing — set `only_contract_assertions`. |
| `result_types` | Which results fire the rule (default `["FAILURE"]`; also `ERROR`, `SUCCESS`). |
| `only_contract_assertions` | Restrict to assertions that back a Data Contract. |
| `filter.domains` / `filter.tags` / `filter.platforms` | Narrow by domain (urn/name), tag urn, or platform key (e.g. `databricks`). |
| `filter.asset_urn_regex` | Regex against the dataset URN. |
| `filter.assertion_types` / `filter.severities` | Narrow by assertion type / failure severity. |

### Sinks

| `type` | Sends |
| ------ | ----- |
| `webhook` | HTTP POST with a default JSON envelope, or your own `json_template`; auth: `bearer` / `basic` / `hmac`. |
| `rest` | Arbitrary method/url/body (`body_template`, `content_type`); same auth options. |
| `jira` | Creates an issue (`base_url`, `username`, `api_token`, `project_key`, `issue_type`). |
| `servicenow` | Inserts a record into `table` (basic auth). |
| `chat` | Slack or Teams incoming webhook. |

Every sink supports `summary_template` / `body_template` and `dry_run`. Templates
use `{placeholder}` names from the alert context (see below); a missing
placeholder renders empty.

### Template placeholders

`result_type`, `severity`, `asset_name`, `asset_urn`, `platform`, `domain_name`,
`domain_urn`, `assertion_type`, `assertion_description`, `assertion_urn`,
`contract_urn`, `owners`, `row_count`, `unexpected_count`, `missing_count`,
`actual_value`, `external_url`, `executed_query`, `run_id`, `run_time`,
`datahub_url`, `idempotency_key`.

## Durability & delivery guarantees

The Actions framework delivers events **at-least-once** (the remote runner
explicitly warns duplicates are possible), and there is **no exactly-once**
option. This action therefore targets **at-least-once processing with
effectively-once side effects** — it never silently drops a failure, and it never
opens duplicate tickets:

- **No missed events.** The Cloud remote source resumes from a durable offset, so
  events during downtime are replayed on restart. On a **permanent** sink failure
  (all retries exhausted) `act()` **raises** instead of swallowing, so the event
  is _not_ acked and gets replayed rather than lost. (Set `failure_mode: THROW`
  and a small `retry_count` on the pipeline for the strongest behaviour.)
- **Transient failures retried in-process.** 5xx / 429 / timeouts / connection
  errors are retried with exponential backoff (`retry` config: `max_attempts`,
  `backoff_seconds`, `backoff_multiplier`, `max_backoff_seconds`). 4xx and bad
  templates fail fast.
- **No duplicate tickets on replay.** Every alert carries a stable
  `idempotency_key` (`{assertion_urn}:{run_id}`). It is sent in webhook/REST
  payloads and as an `Idempotency-Key` header; **Jira** searches for an existing
  issue by a derived label before creating, and **ServiceNow** sets/searches
  `correlation_id`. A replay finds the ticket it already opened instead of making
  a new one — closing the gap a dedup marker alone cannot (crash between dispatch
  and marker write).
- **Dedup marker (on by default).** `use_structured_property` persists the
  last-handled run timestamp on the assertion so replays never re-fire a handled
  run. Register the property once with `python scripts/setup_dedup_property.py`;
  if it is missing, dedup degrades gracefully to the transition + idempotency
  layers (one warning, then silent).

> The marker is recorded only when **every** sink for a rule succeeds, so a
> partial failure re-fires on replay and relies on sink-level idempotency to avoid
> duplicates.

## Deduplication layers (DataHub-side, no external store)

- **`only_on_transition`** (default true) — fire only on a SUCCESS/ERROR→FAILURE
  transition, so a persistently-failing check does not open a ticket every run.
- **`use_structured_property`** (default true) — persist the last-handled run
  timestamp on the assertion so a restart/replay never re-fires a handled run.
  Register the property once with `python scripts/setup_dedup_property.py`.

> With multiple rules targeting the same assertion, prefer the transition layer;
> the structured-property marker stores a single timestamp per assertion, so it is
> best paired with one alerting rule per assertion.

## Install

```bash
pip install -e ".[dev]"
```

## Configure & run

```bash
export DATAHUB_TOKEN=...
export JIRA_API_TOKEN=...          # or SLACK_WEBHOOK_URL / WEBHOOK_HMAC_SECRET
datahub actions -c examples/contract_fail_to_jira.yaml
```

- **DataHub Cloud (managed executor)** — `RemoteActionSource`, config under
  `source.config.action_spec`; add the wheel under **Step 5 → Advanced → Extra
  Pip Libraries**. See `examples/example_action.yaml`.
- **Local / self-hosted** — `datahub-cloud` source + top-level `action:`.

Set `dry_run: true` (global or per sink) to log every dispatch without making
external calls.

## Develop

```bash
make install-dev
make format      # ruff format + fix
make lint        # ruff check
make type-check  # mypy
make test        # pytest (no external services)
```

## License

Apache-2.0
