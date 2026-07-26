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
          ─▶ match rules ─▶ dedup ─▶ dispatch to sinks
                                       (webhook | rest | jira | servicenow | chat)

Startup catchup (each scheduled run):
      search assertions whose latest result is FAILURE ─▶ same pipeline
```

Because the DataHub Cloud executor reaps idle actions, run this on a **schedule**
(every 5–15 min). Each run does a catchup pass then listens for live events.

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
`datahub_url`.

## Deduplication (DataHub-side, no external store)

- **`only_on_transition`** (default true) — fire only on a SUCCESS/ERROR→FAILURE
  transition, so a persistently-failing check does not open a ticket every run.
- **`use_structured_property`** (optional) — persist the last-handled run
  timestamp on the assertion so a restart/catchup never re-fires a handled run.
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
