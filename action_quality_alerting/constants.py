"""Event/aspect names, GraphQL queries, and default templates.

Kept in one place so the DataHub-facing strings and the (long) GraphQL bodies do
not clutter the logic modules.
"""

# --- MCL event routing --------------------------------------------------------

MCL_EVENT_TYPE = "MetadataChangeLogEvent_v1"

ASSERTION_ENTITY = "assertion"
ASSERTION_RUN_EVENT_ASPECT = "assertionRunEvent"

DATA_CONTRACT_ENTITY = "dataContract"
DATA_CONTRACT_STATUS_ASPECT = "dataContractStatus"

# AssertionResultType values (metadata-models: AssertionResultType.pdl).
RESULT_SUCCESS = "SUCCESS"
RESULT_FAILURE = "FAILURE"
RESULT_ERROR = "ERROR"
RESULT_INIT = "INIT"

# AssertionRunStatus — we only act on completed runs.
RUN_STATUS_COMPLETE = "COMPLETE"

# --- Dedup structured property (optional, registered via scripts/) ------------

DEDUP_PROPERTY_QUALIFIED_NAME = "datahub_quality_alerting_last_handled_run"

# --- GraphQL ------------------------------------------------------------------

# Enrich the failing dataset: name, platform, owners (with email), domain, and
# whether it is fronted by a Data Contract. Parsing is defensive — any field that
# a given DataHub Cloud version does not expose simply resolves to None.
ENRICH_DATASET_QUERY = """
query enrichDataset($urn: String!) {
  dataset(urn: $urn) {
    urn
    name
    properties { name qualifiedName }
    platform { name properties { displayName } }
    domain { domain { urn properties { name } } }
    tags { tags { tag { urn } } }
    ownership {
      owners {
        owner {
          ... on CorpUser { urn properties { email displayName } }
          ... on CorpGroup { urn properties { displayName email } }
        }
        ownershipType { urn }
      }
    }
    contract {
      urn
      properties {
        freshness { assertion { urn } }
        schema { assertion { urn } }
        dataQuality { assertion { urn } }
      }
    }
  }
}
"""

# Fetch the two most recent completed runs of an assertion so we can tell whether
# this failure is a *new* failure (SUCCESS/ERROR -> FAILURE transition) rather
# than the Nth consecutive failing run.
ASSERTION_RUN_HISTORY_QUERY = """
query assertionRuns($urn: String!) {
  assertion(urn: $urn) {
    urn
    info {
      type
      description
      datasetAssertion { datasetUrn scope }
    }
    runEvents(status: COMPLETE, limit: 2) {
      total
      runEvents {
        timestampMillis
        result { type }
      }
    }
  }
}
"""

# Catchup: find assertions whose most recent result is FAILURE. `lastResultType`
# is @Searchable on AssertionResult (metadata-models). Aggregation/search on it is
# uncapped enough for our batch sizes.
SEARCH_FAILED_ASSERTIONS_QUERY = """
query failedAssertions($start: Int!, $count: Int!, $resultTypes: [String!]!) {
  searchAcrossEntities(
    input: {
      types: [ASSERTION]
      query: "*"
      start: $start
      count: $count
      orFilters: [{ and: [{ field: "lastResultType", values: $resultTypes }] }]
    }
  ) {
    total
    searchResults { entity { urn } }
  }
}
"""

# Optional durable dedup marker: read/write a numeric structured property that
# holds the last-handled run timestamp on the assertion entity.
GET_ASSERTION_MARKER_QUERY = """
query assertionMarker($urn: String!) {
  assertion(urn: $urn) {
    structuredProperties {
      properties {
        structuredProperty { urn }
        values { ... on NumberValue { numberValue } ... on StringValue { stringValue } }
      }
    }
  }
}
"""

UPSERT_MARKER_MUTATION = """
mutation upsertMarker($input: UpsertStructuredPropertiesInput!) {
  upsertStructuredProperties(input: $input) { properties { structuredProperty { urn } } }
}
"""

# --- Default templates (Python str.format placeholders) -----------------------

DEFAULT_SUMMARY_TEMPLATE = "[DataHub] {result_type} on {asset_name}"

DEFAULT_BODY_TEMPLATE = (
    "A DataHub {trigger} produced result {result_type}.\n\n"
    "Asset: {asset_name} ({asset_urn})\n"
    "Platform: {platform}\n"
    "Domain: {domain_name}\n"
    "Assertion: {assertion_description} ({assertion_urn})\n"
    "Contract: {contract_urn}\n"
    "Owners: {owners}\n"
    "Severity: {severity}\n"
    "Observed: rows={row_count} unexpected={unexpected_count} value={actual_value}\n"
    "Run at: {run_time}\n"
    "Details: {external_url}\n"
)
