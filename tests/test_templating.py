import pytest

from action_quality_alerting.templating import render, render_json


def test_render_missing_key_is_empty():
    assert render("a={a} b={b}", {"a": "1"}) == "a=1 b="


def test_render_json_escapes_quotes_and_newlines():
    variables = {"summary": 'he said "hi"\nline2'}
    out = render_json('{"text": "{summary}"}', variables)
    assert out == {"text": 'he said "hi"\nline2'}


def test_render_json_invalid_raises():
    with pytest.raises(ValueError):
        render_json('{"text": {summary}}', {"summary": "not-json"})
