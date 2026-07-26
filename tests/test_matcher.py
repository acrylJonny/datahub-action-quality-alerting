from action_quality_alerting.config import MatchConfig, MatchFilter
from action_quality_alerting.enrich import MatchFacts
from action_quality_alerting.matcher import matches


def _facts(**kw) -> MatchFacts:
    base = dict(
        result_type="FAILURE",
        severity="HIGH",
        assertion_type="FRESHNESS",
        asset_urn="urn:li:dataset:(urn:li:dataPlatform:databricks,cat.sch.tbl,PROD)",
        platform_key="databricks",
        domain_urn="urn:li:domain:finance",
        tags=["urn:li:tag:pii"],
        is_contract_assertion=True,
    )
    base.update(kw)
    return MatchFacts(**base)


def test_result_type_filter():
    assert matches(MatchConfig(result_types=["FAILURE"]), _facts())
    assert not matches(MatchConfig(result_types=["ERROR"]), _facts())


def test_only_contract_assertions():
    m = MatchConfig(result_types=["FAILURE"], only_contract_assertions=True)
    assert matches(m, _facts(is_contract_assertion=True))
    assert not matches(m, _facts(is_contract_assertion=False))


def test_platform_and_domain_and_tag_filters():
    m = MatchConfig(
        result_types=["FAILURE"],
        filter=MatchFilter(
            platforms=["Databricks"],  # case-insensitive
            domains=["urn:li:domain:finance"],
            tags=["urn:li:tag:pii"],
        ),
    )
    assert matches(m, _facts())
    assert not matches(m, _facts(platform_key="snowflake"))
    assert not matches(m, _facts(tags=["urn:li:tag:other"]))


def test_asset_urn_regex():
    m = MatchConfig(result_types=["FAILURE"], filter=MatchFilter(asset_urn_regex=r"cat\.sch\."))
    assert matches(m, _facts())
    assert not matches(m, _facts(asset_urn="urn:li:dataset:(...,other.x.y,PROD)"))


def test_severity_filter():
    m = MatchConfig(result_types=["FAILURE"], filter=MatchFilter(severities=["HIGH"]))
    assert matches(m, _facts(severity="HIGH"))
    assert not matches(m, _facts(severity="LOW"))
