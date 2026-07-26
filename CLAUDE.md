# CLAUDE.md

Guidance for agents working in this repository.

## What this is

A DataHub Action that reacts to assertion / data-contract validation results and
triggers external actions (webhook, REST, Jira, ServiceNow, Slack/Teams). It is a
sibling of `datahub-action-access-provisioner` and follows the same conventions.

## Architecture (one module per duty)

| Module | Duty |
| --- | --- |
| `constants.py` | Event/aspect names, GraphQL queries, default templates |
| `config.py` | Pydantic v2 config: rules, match, sinks (discriminated union), dedup |
| `models.py` | Parsed run outcome, alert context, dispatch result |
| `graphql.py` | Defensive GraphQL read helpers + field extractors |
| `enrich.py` | Build the alert context + flat match facts from an outcome |
| `matcher.py` | Evaluate a rule's match config against the facts |
| `templating.py` | Safe `{placeholder}` rendering (missing → empty; JSON-escaped) |
| `dedup.py` | DataHub-side dedup: transition detection + optional SP marker |
| `sinks/` | One module per outbound target + `dispatch()` registry |
| `quality_alerting_action.py` | The `Action`: live `act()` + startup catchup |

## Event model (metadata-models, datahub-fork)

- Trigger: `MetadataChangeLogEvent`, `entityType=assertion`,
  `aspectName=assertionRunEvent`.
- The aspect carries `result.type` ∈ {SUCCESS, FAILURE, ERROR, INIT},
  `asserteeUrn` (dataset), `assertionUrn`, severity, counts.
- A data-contract breach == one of the contract's bound assertions failing, so it
  is handled via `match.only_contract_assertions` rather than a separate trigger.

## Conventions

- Python 3.10+, Pydantic v2, `str | None` unions, builtin generics.
- `requests` is imported lazily inside `sinks/http.py` (provided by the executor
  runtime, not a hard dependency).
- All GraphQL reads degrade to `None`/`{}` on error — alerting must never crash on
  a field a given DataHub version does not expose.
- Comments explain *why*, not *what*. No top-of-file narration.
- New sink: add a config model in `config.py` (with a `type` literal, add to the
  `SinkConfig` union), a module under `sinks/`, and a branch in `sinks/dispatch`.

## Commands

```bash
make install-dev
make lint && make type-check && make test
```

Tests must not hit any external service or a live DataHub — use dry-run sinks and
in-memory fixtures.
