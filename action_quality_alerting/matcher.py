"""Evaluate a rule's match config against the enriched facts of an event."""

import re
from functools import lru_cache
from re import Pattern

from action_quality_alerting.config import MatchConfig
from action_quality_alerting.enrich import MatchFacts


@lru_cache(maxsize=64)
def _compiled(pattern: str) -> Pattern[str]:
    return re.compile(pattern)


def _regex_ok(pattern: str | None, value: str | None) -> bool:
    if not pattern:
        return True
    return value is not None and _compiled(pattern).search(value) is not None


def matches(match: MatchConfig, facts: MatchFacts) -> bool:
    if match.result_types and facts.result_type not in match.result_types:
        return False

    if match.only_contract_assertions and not facts.is_contract_assertion:
        return False

    flt = match.filter

    if flt.domains and not (
        (facts.domain_urn in flt.domains) or (facts.domain_name in flt.domains)
    ):
        return False

    if flt.tags and not (set(flt.tags) & set(facts.tags)):
        return False

    if flt.platforms:
        wanted = {p.lower() for p in flt.platforms}
        if (facts.platform_key or "") not in wanted:
            return False

    if not _regex_ok(flt.asset_urn_regex, facts.asset_urn):
        return False

    if flt.assertion_types and facts.assertion_type not in flt.assertion_types:
        return False

    if flt.severities and facts.severity not in flt.severities:
        return False

    return True
