"""Poll-Durchlauf: Feeds lesen, neue Artikel konvertieren, optional pushen."""

import logging
import time
from pathlib import Path

import httpx

from medienpaed_reader.article_page import (
    choose_main_pdf,
    download_pdf,
    fetch_article_meta,
)
from medienpaed_reader.config import Settings
from medienpaed_reader.feed_source import fetch_feed
from medienpaed_reader.pdf_convert import PdfConverter
from medienpaed_reader.readwise import ReadwiseClient
from medienpaed_reader.sources import Source
from medienpaed_reader.store import ArticleRecord, Store
from medienpaed_reader.web_extract import fetch_article

log = logging.getLogger(__name__)


def make_http_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )


def discover(settings: Settings, store: Store, client: httpx.Client) -> int:
    """Neue Feed-Eintraege aller Quellen als pending vormerken."""
    total_new = 0
    for source in settings.sources.values():
        try:
            entries = fetch_feed(client, source.feed_url, source.type)
        except httpx.HTTPError as exc:
            log.error("Feed %s nicht abrufbar: %s", source.key, exc)
            continue
        known = store.known_ids(source.key)
        new = 0
        for entry in entries:
            if entry.article_id in known:
                continue
            store.upsert_pending(source.key, entry.article_id, entry.link, entry.title)
            new += 1
        log.info("Feed %s: %d Eintraege, %d neu", source.key, len(entries), new)
        total_new += new
    return total_new


def process_article(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter | None,
    record: ArticleRecord,
) -> None:
    source = settings.sources[record.source]
    if source.type == "web":
        _process_web_article(settings, store, client, record)
    else:
        if converter is None:
            raise RuntimeError("PDF-Konverter fehlt fuer OJS-Quelle")
        _process_ojs_article(settings, store, client, converter, record)


def _process_ojs_article(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter,
    record: ArticleRecord,
) -> None:
    meta = fetch_article_meta(client, record.article_id, record.landing_url)
    pdf_url = choose_main_pdf(client, meta.pdf_urls)
    if pdf_url is None:
        raise ValueError("Artikelseite enthaelt kein citation_pdf_url")

    pdf_path = settings.pdf_dir / record.source / f"{record.article_id}.pdf"
    html_path = settings.html_dir / record.source / f"{record.article_id}.html"
    md_path = html_path.with_suffix(".md")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    download_pdf(client, pdf_url, str(pdf_path))
    converter.convert(pdf_path, html_path, md_path)

    store.mark_done(
        record.source,
        record.article_id,
        title=meta.title,
        authors=meta.authors,
        published=meta.published.isoformat() if meta.published else None,
        doi=meta.doi,
        language=meta.language,
        abstract=meta.abstract,
        pdf_url=pdf_url,
        html_path=str(html_path),
    )
    log.info("Artikel %s/%d fertig: %s", record.source, record.article_id, meta.title)


def _process_web_article(
    settings: Settings, store: Store, client: httpx.Client, record: ArticleRecord
) -> None:
    article = fetch_article(client, record.landing_url, record.title)
    html_path = settings.html_dir / record.source / f"{record.article_id}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(article.html, encoding="utf-8")

    store.mark_done(
        record.source,
        record.article_id,
        title=article.title,
        authors=article.authors,
        published=article.published.isoformat() if article.published else None,
        doi=None,
        language=article.language,
        abstract=article.description,
        pdf_url=None,
        html_path=str(html_path),
    )
    log.info(
        "Artikel %s/%d fertig: %s", record.source, record.article_id, article.title
    )


def process_pending(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter | None,
    limit: int | None = None,
) -> int:
    pending = store.pending(limit or settings.max_articles_per_poll)
    done = 0
    for record in pending:
        if record.source not in settings.sources:
            log.warning(
                "Artikel %s/%d: Quelle nicht konfiguriert, uebersprungen",
                record.source,
                record.article_id,
            )
            continue
        try:
            process_article(settings, store, client, converter, record)
            done += 1
        except Exception as exc:  # noqa: BLE001 - Fehler pro Artikel isolieren
            log.exception(
                "Artikel %s/%d fehlgeschlagen", record.source, record.article_id
            )
            store.mark_failed(
                record.source, record.article_id, repr(exc), settings.max_attempts
            )
    return done


def push_unpushed(settings: Settings, store: Store, dry_run: bool = False) -> int:
    if not settings.readwise_token:
        log.warning("READWISE_TOKEN fehlt, Push uebersprungen")
        return 0
    rw = ReadwiseClient(settings.readwise_token)
    pushed = 0
    for record in store.unpushed():
        source = settings.sources.get(record.source)
        if not record.html_path or source is None:
            continue
        html = Path(record.html_path).read_text(encoding="utf-8")
        if dry_run:
            log.info(
                "dry-run: wuerde pushen %s/%d %s",
                record.source,
                record.article_id,
                record.title,
            )
            continue
        # Reader zeigt die Domain der URL als Quelle an; mit dem DOI-Link stuende
        # dort "doi.org". Die Artikelseite ist ebenso eindeutig fuer die Deduplizierung.
        rw.save_html(
            url=record.landing_url,
            html=wrap_html(record, source, html),
            title=record.title,
            author=", ".join(record.authors) or None,
            published_date=record.published,
            tags=source.tags,
            location=settings.readwise_location,
            summary=record.abstract,
        )
        store.mark_pushed(record.source, record.article_id)
        pushed += 1
    return pushed


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


def run_once(
    settings: Settings,
    store: Store,
    converter: PdfConverter | None = None,
    limit: int | None = None,
    skip_discover: bool = False,
) -> None:
    settings.ensure_dirs()
    with make_http_client(settings) as client:
        if not skip_discover:
            discover(settings, store, client)
        needs_pdf = any(
            settings.sources.get(r.source) is not None
            and settings.sources[r.source].type == "ojs"
            for r in store.pending(limit or settings.max_articles_per_poll)
        )
        if converter is None and needs_pdf:
            converter = PdfConverter(
                settings.docling_artifacts_path, settings.docling_threads
            )
        process_pending(settings, store, client, converter, limit)
    if settings.readwise_push:
        push_unpushed(settings, store)


def repush_doi_documents(
    settings: Settings, store: Store, dry_run: bool = False
) -> tuple[int, int]:
    """Von uns angelegte Reader-Dokumente mit doi.org-URL loeschen und neu pushen.

    Fruehere Versionen uebergaben den DOI-Link als URL, wodurch Reader "doi.org"
    als Quelle anzeigte. Die URL laesst sich per API nicht aendern, nur neu anlegen.
    Gibt (geloescht, neu gepusht) zurueck.
    """
    if not settings.readwise_token:
        raise RuntimeError("READWISE_TOKEN fehlt")
    rw = ReadwiseClient(settings.readwise_token)
    seen: set[str] = set()
    targets: list[dict] = []
    for source in settings.sources.values():
        tag = source.tags[0]
        for doc in rw.list_documents(tag):
            if doc["id"] in seen:
                continue
            seen.add(doc["id"])
            # Die List-API liefert saved_using nicht zurueck; unser Kennzeichen ist
            # der per API gesetzte Quellen-Tag zusammen mit der doi.org-URL.
            tag_info = (doc.get("tags") or {}).get(tag) or {}
            if tag_info.get("type") == "public_api" and "doi.org" in (
                doc.get("source_url") or ""
            ):
                targets.append(doc)
    log.info("Reader: %d eigene Dokumente mit doi.org-URL", len(targets))
    if dry_run:
        for doc in targets:
            log.info("dry-run: wuerde loeschen %s %s", doc["id"], doc.get("title"))
        return 0, 0

    deleted = 0
    for doc in targets:
        rw.delete_document(doc["id"])
        deleted += 1
        log.info("Reader: geloescht %s", doc.get("title"))
        time.sleep(3.1)  # Delete-Endpunkt: 20 Anfragen pro Minute
    for record in store.done(limit=100_000):
        if record.readwise_pushed_at:
            store.reset_pushed(record.source, record.article_id)
    pushed = push_unpushed(settings, store)
    return deleted, pushed
