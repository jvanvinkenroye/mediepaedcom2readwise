"""Poll-Durchlauf: Feed lesen, neue Artikel konvertieren, optional pushen."""

import logging
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
from medienpaed_reader.store import ArticleRecord, Store

log = logging.getLogger(__name__)


def make_http_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )


def discover(settings: Settings, store: Store, client: httpx.Client) -> int:
    """Neue Feed-Eintraege als pending vormerken; gibt Anzahl neuer Artikel zurueck."""
    entries = fetch_feed(client, settings.feed_url)
    known = store.known_ids()
    new = 0
    for entry in entries:
        if entry.article_id in known:
            continue
        store.upsert_pending(entry.article_id, entry.link, entry.title)
        new += 1
    log.info("Feed: %d Eintraege, %d neu", len(entries), new)
    return new


def process_article(
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

    pdf_path = settings.pdf_dir / f"{record.article_id}.pdf"
    html_path = settings.html_dir / f"{record.article_id}.html"
    md_path = settings.html_dir / f"{record.article_id}.md"
    download_pdf(client, pdf_url, str(pdf_path))
    converter.convert(pdf_path, html_path, md_path)

    store.mark_done(
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
    log.info("Artikel %d fertig: %s", record.article_id, meta.title)


def process_pending(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter,
    limit: int | None = None,
) -> int:
    pending = store.pending(limit or settings.max_articles_per_poll)
    done = 0
    for record in pending:
        try:
            process_article(settings, store, client, converter, record)
            done += 1
        except Exception as exc:  # noqa: BLE001 - Fehler pro Artikel isolieren
            log.exception("Artikel %d fehlgeschlagen", record.article_id)
            store.mark_failed(record.article_id, repr(exc), settings.max_attempts)
    return done


def push_unpushed(settings: Settings, store: Store, dry_run: bool = False) -> int:
    if not settings.readwise_token:
        log.warning("READWISE_TOKEN fehlt, Push uebersprungen")
        return 0
    rw = ReadwiseClient(settings.readwise_token)
    pushed = 0
    for record in store.unpushed():
        if not record.html_path:
            continue
        html = Path(record.html_path).read_text(encoding="utf-8")
        if dry_run:
            log.info("dry-run: wuerde pushen %d %s", record.article_id, record.title)
            continue
        rw.save_html(
            url=record.doi_url or record.landing_url,
            html=_wrap_html(record, html),
            title=record.title,
            author=", ".join(record.authors) or None,
            published_date=record.published,
            tags=settings.readwise_tags,
            location=settings.readwise_location,
            summary=record.abstract,
        )
        store.mark_pushed(record.article_id)
        pushed += 1
    return pushed


def _wrap_html(record: ArticleRecord, body: str) -> str:
    links = [f'<a href="{record.landing_url}">Artikelseite</a>']
    if record.doi_url:
        links.append(f'<a href="{record.doi_url}">DOI</a>')
    if record.pdf_url:
        links.append(f'<a href="{record.pdf_url}">PDF</a>')
    header = "<p>" + " · ".join(links) + " · MedienPädagogik, CC BY 4.0</p>"
    return f"<html><body>{header}{body}</body></html>"


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
        if converter is None:
            converter = PdfConverter(
                settings.docling_artifacts_path, settings.docling_threads
            )
        process_pending(settings, store, client, converter, limit)
    if settings.readwise_push:
        push_unpushed(settings, store)
