import json

import httpx
import pytest
import respx

from medienpaed_reader.readwise import READWISE_SAVE_URL, ReadwiseClient


def _client() -> ReadwiseClient:
    return ReadwiseClient("secret-token", client=httpx.Client())


@respx.mock
def test_save_html_sends_expected_payload() -> None:
    route = respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(
            201, json={"id": "abc", "url": "https://read.readwise.io/x"}
        )
    )
    result = _client().save_html(
        url="https://doi.org/10.1/x",
        html="<p>Hi</p>",
        title="T",
        author="A",
        published_date="2026-07-20",
        tags=["medienpaed"],
        location="feed",
    )
    assert result.created is True
    assert result.document_id == "abc"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Token secret-token"
    payload = json.loads(request.content)
    assert payload["url"] == "https://doi.org/10.1/x"
    assert payload["html"] == "<p>Hi</p>"
    assert payload["tags"] == ["medienpaed"]
    assert payload["location"] == "feed"
    assert payload["category"] == "article"
    assert payload["should_clean_html"] is False


@respx.mock
def test_save_html_reports_duplicate() -> None:
    respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(200, json={"id": "abc"})
    )
    result = _client().save_html(
        url="u",
        html="h",
        title="t",
        author=None,
        published_date=None,
        tags=[],
        location="new",
    )
    assert result.created is False


@respx.mock
def test_save_html_raises_on_rate_limit() -> None:
    respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    with pytest.raises(httpx.HTTPStatusError, match="Retry-After=30"):
        _client().save_html(
            url="u",
            html="h",
            title="t",
            author=None,
            published_date=None,
            tags=[],
            location="new",
        )
