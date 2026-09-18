"""Optionaler Push in Readwise Reader ueber die v3-API."""

import logging
import time
from dataclasses import dataclass

import httpx

READWISE_SAVE_URL = "https://readwise.io/api/v3/save/"
READWISE_LIST_URL = "https://readwise.io/api/v3/list/"
READWISE_DELETE_URL = "https://readwise.io/api/v3/delete/{id}/"
READWISE_AUTH_URL = "https://readwise.io/api/v2/auth/"
SAVED_USING = "medienpaed-reader"

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
            "saved_using": SAVED_USING,
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

    def list_documents(self, tag: str) -> list[dict]:
        """Alle Reader-Dokumente mit einem Tag, ueber alle Seiten hinweg."""
        docs: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"tag": tag}
            if cursor:
                params["pageCursor"] = cursor
            response = self._client.get(
                READWISE_LIST_URL, params=params, headers=self._headers
            )
            response.raise_for_status()
            data = response.json()
            docs.extend(data.get("results", []))
            cursor = data.get("nextPageCursor")
            if not cursor:
                return docs

    def delete_document(self, document_id: str, max_retries: int = 5) -> None:
        """Dokument loeschen; bei 429 nach Retry-After erneut versuchen."""
        for attempt in range(max_retries + 1):
            response = self._client.delete(
                READWISE_DELETE_URL.format(id=document_id), headers=self._headers
            )
            if response.status_code != 429 or attempt == max_retries:
                response.raise_for_status()
                return
            wait = int(response.headers.get("Retry-After", "60"))
            log.warning("Readwise: Rate-Limit beim Loeschen, warte %ds", wait)
            time.sleep(wait + 1)

    def find_by_url(self, tag: str, url: str) -> list[dict]:
        """Eigene Dokumente (Tag per API gesetzt) mit genau dieser Quell-URL."""
        return [
            doc
            for doc in self.list_documents(tag)
            if doc.get("source_url") == url
            and ((doc.get("tags") or {}).get(tag) or {}).get("type") == "public_api"
        ]
