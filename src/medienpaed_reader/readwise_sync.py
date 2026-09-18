"""Abgleich der fertigen Artikel mit Readwise Reader."""

import logging
import time
from enum import Enum
from pathlib import Path

import httpx

from medienpaed_reader.config import Settings
from medienpaed_reader.readwise import ReadwiseClient
from medienpaed_reader.sources import Source
from medienpaed_reader.store import ArticleRecord, Store

log = logging.getLogger(__name__)

# Der Delete-Endpunkt erlaubt 20 Anfragen pro Minute.
DELETE_PAUSE_SECONDS = 3.1


class PushOutcome(Enum):
    PUSHED = "pushed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


def source_line(record: ArticleRecord, source: Source) -> str:
    """Kopfzeile mit Quelle und Lizenz, fuer Feed-Items und Readwise."""
    parts = [f'<a href="{record.landing_url}">Artikelseite</a>']
    if record.doi_url:
        parts.append(f'<a href="{record.doi_url}">DOI</a>')
    if record.pdf_url:
        parts.append(f'<a href="{record.pdf_url}">PDF</a>')
    label = source.name + (f", {source.license}" if source.license else "")
    parts.append(label)
    return "<p>" + " · ".join(parts) + "</p>"


def wrap_html(record: ArticleRecord, source: Source, body: str) -> str:
    return f"<html><body>{source_line(record, source)}{body}</body></html>"


def _client(settings: Settings) -> ReadwiseClient:
    if not settings.readwise_token:
        raise RuntimeError("READWISE_TOKEN fehlt")
    return ReadwiseClient(settings.readwise_token)


def _push_record(
    rw: ReadwiseClient, settings: Settings, record: ArticleRecord, source: Source
) -> PushOutcome:
    body = Path(record.html_path or "").read_text(encoding="utf-8")
    try:
        # Reader zeigt die Domain der URL als Quelle an; mit dem DOI-Link stuende
        # dort "doi.org". Die Artikelseite ist ebenso eindeutig fuer die Deduplizierung.
        rw.save_html(
            url=record.landing_url,
            html=wrap_html(record, source, body),
            title=record.title,
            author=", ".join(record.authors) or None,
            published_date=record.published,
            tags=source.tags,
            location=settings.readwise_location,
            summary=record.abstract,
        )
    except httpx.HTTPStatusError as exc:
        log.error(
            "Readwise-Push %s/%d fehlgeschlagen: %s",
            record.source,
            record.article_id,
            exc,
        )
        if exc.response.status_code == 429:
            return PushOutcome.RATE_LIMITED
        return PushOutcome.FAILED
    except httpx.HTTPError as exc:
        log.error(
            "Readwise-Push %s/%d Netzwerkfehler: %s",
            record.source,
            record.article_id,
            exc,
        )
        return PushOutcome.FAILED
    return PushOutcome.PUSHED


def push_unpushed(settings: Settings, store: Store, dry_run: bool = False) -> int:
    """Alle fertigen, noch nicht gepushten Artikel anlegen; Fehler pro Artikel."""
    if not settings.readwise_token:
        log.warning("READWISE_TOKEN fehlt, Push uebersprungen")
        return 0
    rw = ReadwiseClient(settings.readwise_token)
    pushed = 0
    for record in store.unpushed():
        source = settings.sources.get(record.source)
        if not record.html_path or source is None:
            continue
        if dry_run:
            log.info(
                "dry-run: wuerde pushen %s/%d %s",
                record.source,
                record.article_id,
                record.title,
            )
            continue
        outcome = _push_record(rw, settings, record, source)
        if outcome is PushOutcome.RATE_LIMITED:
            # Weitere Versuche im selben Durchlauf sind sinnlos.
            break
        if outcome is PushOutcome.PUSHED:
            store.mark_pushed(record.source, record.article_id)
            pushed += 1
    return pushed


def _is_own_document(doc: dict, tag: str) -> bool:
    """Die List-API liefert saved_using nicht; unser Kennzeichen ist der API-Tag."""
    tag_info = (doc.get("tags") or {}).get(tag) or {}
    return tag_info.get("type") == "public_api"


def find_doi_documents(rw: ReadwiseClient, settings: Settings) -> list[dict]:
    """Eigene Reader-Dokumente, deren URL noch auf doi.org zeigt."""
    seen: set[str] = set()
    targets: list[dict] = []
    for source in settings.sources.values():
        tag = source.tags[0]
        for doc in rw.list_documents(tag):
            if doc["id"] in seen:
                continue
            seen.add(doc["id"])
            if _is_own_document(doc, tag) and "doi.org" in (
                doc.get("source_url") or ""
            ):
                targets.append(doc)
    return targets


def _delete_documents(rw: ReadwiseClient, docs: list[dict]) -> int:
    for doc in docs:
        rw.delete_document(doc["id"])
        log.info("Reader: geloescht %s", doc.get("title"))
        time.sleep(DELETE_PAUSE_SECONDS)
    return len(docs)


def repush_doi_documents(
    settings: Settings, store: Store, dry_run: bool = False
) -> tuple[int, int]:
    """Von uns angelegte Reader-Dokumente mit doi.org-URL loeschen und neu pushen.

    Fruehere Versionen uebergaben den DOI-Link als URL, wodurch Reader "doi.org"
    als Quelle anzeigte. Die URL laesst sich per API nicht aendern, nur neu anlegen.
    Gibt (geloescht, neu gepusht) zurueck.
    """
    rw = _client(settings)
    targets = find_doi_documents(rw, settings)
    log.info("Reader: %d eigene Dokumente mit doi.org-URL", len(targets))
    if dry_run:
        for doc in targets:
            log.info("dry-run: wuerde loeschen %s %s", doc["id"], doc.get("title"))
        return 0, 0

    deleted = _delete_documents(rw, targets)
    for record in store.done(limit=100_000):
        if record.readwise_pushed_at:
            store.reset_pushed(record.source, record.article_id)
    return deleted, push_unpushed(settings, store)


def forget_in_readwise(settings: Settings, store: Store, record: ArticleRecord) -> int:
    """Reader-Dokument eines Artikels loeschen und Push-Markierung zuruecksetzen."""
    rw = _client(settings)
    source = settings.sources[record.source]
    docs = rw.find_by_url(source.tags[0], record.landing_url)
    deleted = _delete_documents(rw, docs)
    store.reset_pushed(record.source, record.article_id)
    return deleted
