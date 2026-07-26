"""Template rendering.

Uses ``{name}`` token substitution via regex rather than ``str.format`` so that
JSON templates (whose own ``{}`` would collide with format fields) work without
escaping. Unknown tokens render as empty strings; JSON templates get their
substituted values escaped so free-text with quotes/newlines stays valid JSON.
"""

import json
import re
from typing import Any

# Matches a single {placeholder}; other braces (e.g. JSON structure) are left as-is.
_TOKEN_RE = re.compile(r"\{(\w+)\}")


def render(template: str, variables: dict[str, str]) -> str:
    return _TOKEN_RE.sub(lambda m: variables.get(m.group(1), ""), template)


def _json_escaped(variables: dict[str, str]) -> dict[str, str]:
    # json.dumps('a"b') -> '"a\\"b"'; stripping the outer quotes yields a value
    # safe to embed inside a JSON string literal in the template.
    return {
        key: json.dumps("" if value is None else str(value))[1:-1]
        for key, value in variables.items()
    }


def render_json(template: str, variables: dict[str, str]) -> Any:
    """Render a JSON body template and parse it. Raises ValueError if the result
    is not valid JSON (surfaced to the caller as a dispatch failure)."""
    rendered = render(template, _json_escaped(variables))
    return json.loads(rendered)
