"""Optionaler Push in Readwise Reader ueber die v3-API."""

import logging
from dataclasses import dataclass

import httpx

READWISE_SAVE_URL = "https://readwise.io/api/v3/save/"
READWISE_AUTH_URL = "https://readwise.io/api/v2/auth/"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaveResult:
    created: bool
    document_id: str | None
    reader_url: str | None


class ReadwiseClient:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=60.0)
        self._headers = {"Authorization": f"Token {token}"}

    def check_auth(self) -> bool:
        response = self._client.get(READWISE_AUTH_URL, headers=self._headers)
        return response.status_code == 204

    def save_html(
        self,
        *,
        url: str,
        html: str,
        title: str,
        author: str | None,
        published_date: str | None,
        tags: list[str],
        location: str,
        summary: str | None = None,
    ) -> SaveResult:
        payload: dict[str, object] = {
            "url": url,
            "html": html,
            "title": title,
            "tags": tags,
            "location": location,
            "category": "article",
            "should_clean_html": False,
            "saved_using": "medienpaed-reader",
        }
        if author:
            payload["author"] = author
        if published_date:
            payload["published_date"] = published_date
        if summary:
            payload["summary"] = summary

        response = self._client.post(
            READWISE_SAVE_URL, json=payload, headers=self._headers
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "?")
            raise httpx.HTTPStatusError(
                f"Readwise rate limit, Retry-After={retry_after}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        data = response.json()
        created = response.status_code == 201
        log.info(
            "Readwise: %s %s", "neu angelegt" if created else "bereits vorhanden", url
        )
        return SaveResult(
            created=created, document_id=data.get("id"), reader_url=data.get("url")
        )
