"""Register the (optional) structured property used for durable dedup.

Only needed if you set ``dedup.use_structured_property: true``. It records the
last-handled assertion run timestamp on each assertion so a restart / catchup
pass never re-fires an alert for a run already handled.

Run once:
    export DATAHUB_GMS_URL=https://your-instance.acryl.io/gms
    export DATAHUB_GMS_TOKEN=...
    python scripts/setup_dedup_property.py
"""

import os

from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph

QUALIFIED_NAME = "datahub_quality_alerting_last_handled_run"

CREATE_PROPERTY_MUTATION = """
mutation createProp($input: CreateStructuredPropertyInput!) {
  createStructuredProperty(input: $input) { urn }
}
"""

PROPERTY_INPUT = {
    "id": QUALIFIED_NAME,
    "qualifiedName": QUALIFIED_NAME,
    "displayName": "Quality Alerting: last handled run",
    "description": "Epoch-millis of the last assertion run for which an alert was dispatched.",
    "valueType": "urn:li:dataType:datahub.number",
    "cardinality": "SINGLE",
    "entityTypes": ["urn:li:entityType:datahub.assertion"],
}


def main() -> None:
    graph = DataHubGraph(
        DatahubClientConfig(
            server=os.environ["DATAHUB_GMS_URL"],
            token=os.environ.get("DATAHUB_GMS_TOKEN"),
        )
    )
    result = graph.execute_graphql(CREATE_PROPERTY_MUTATION, {"input": PROPERTY_INPUT})
    print("Created structured property:", result["createStructuredProperty"]["urn"])


if __name__ == "__main__":
    main()
