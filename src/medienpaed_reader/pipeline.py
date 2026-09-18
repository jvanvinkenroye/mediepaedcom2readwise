"""Poll-Durchlauf: Feeds lesen, neue Artikel konvertieren, optional pushen."""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from medienpaed_reader.article_page import choose_main_pdf, fetch_article_meta
from medienpaed_reader.config import Settings
from medienpaed_reader.feed_source import fetch_feed
from medienpaed_reader.pdf_convert import PdfConverter
from medienpaed_reader.readwise_sync import push_unpushed
from medienpaed_reader.store import ArticleRecord, Store
from medienpaed_reader.web_extract import fetch_article

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArticlePaths:
    pdf: Path
    html: Path

    @property
    def markdown(self) -> Path:
        return self.html.with_suffix(".md")


def article_paths(settings: Settings, record: ArticleRecord) -> ArticlePaths:
    return ArticlePaths(
        pdf=settings.pdf_dir / record.source / f"{record.article_id}.pdf",
        html=settings.html_dir / record.source / f"{record.article_id}.html",
    )


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
        new_entries = [e for e in entries if e.article_id not in known]
        for entry in new_entries:
            store.upsert_pending(source.key, entry.article_id, entry.link, entry.title)
        log.info(
            "Feed %s: %d Eintraege, %d neu", source.key, len(entries), len(new_entries)
        )
        total_new += len(new_entries)
    return total_new


def _finish(
    store: Store,
    record: ArticleRecord,
    *,
    title: str,
    authors: list[str],
    published: date | None,
    html_path: Path,
    doi: str | None = None,
    language: str | None = None,
    abstract: str | None = None,
    pdf_url: str | None = None,
) -> None:
    store.mark_done(
        record.source,
        record.article_id,
        title=title,
        authors=authors,
        published=published.isoformat() if published else None,
        doi=doi,
        language=language,
        abstract=abstract,
        pdf_url=pdf_url,
        html_path=str(html_path),
    )
    log.info("Artikel %s/%d fertig: %s", record.source, record.article_id, title)


def _process_ojs_article(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter,
    record: ArticleRecord,
) -> None:
    paths = article_paths(settings, record)
    meta = fetch_article_meta(client, record.article_id, record.landing_url)
    pdf_url = choose_main_pdf(client, meta.pdf_urls, paths.pdf)
    if pdf_url is None:
        raise ValueError("Artikelseite enthaelt kein citation_pdf_url")
    converter.convert(paths.pdf, paths.html, paths.markdown)
    _finish(
        store,
        record,
        title=meta.title,
        authors=meta.authors,
        published=meta.published,
        html_path=paths.html,
        doi=meta.doi,
        language=meta.language,
        abstract=meta.abstract,
        pdf_url=pdf_url,
    )


def _process_web_article(
    settings: Settings, store: Store, client: httpx.Client, record: ArticleRecord
) -> None:
    paths = article_paths(settings, record)
    article = fetch_article(client, record.landing_url, record.title)
    paths.html.parent.mkdir(parents=True, exist_ok=True)
    paths.html.write_text(article.html, encoding="utf-8")
    _finish(
        store,
        record,
        title=article.title,
        authors=article.authors,
        published=article.published,
        html_path=paths.html,
        abstract=article.description,
    )


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
        return
    if converter is None:
        raise RuntimeError("PDF-Konverter fehlt fuer OJS-Quelle")
    _process_ojs_article(settings, store, client, converter, record)


def process_pending(
    settings: Settings,
    store: Store,
    client: httpx.Client,
    converter: PdfConverter | None,
    limit: int | None = None,
) -> int:
    done = 0
    for record in store.pending(limit or settings.max_articles_per_poll):
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


def _needs_pdf_converter(settings: Settings, store: Store, limit: int) -> bool:
    sources = (settings.sources.get(r.source) for r in store.pending(limit))
    return any(source is not None and source.type == "ojs" for source in sources)


def run_once(
    settings: Settings,
    store: Store,
    converter: PdfConverter | None = None,
    limit: int | None = None,
    skip_discover: bool = False,
) -> PdfConverter | None:
    """Einen Durchlauf ausfuehren; gibt den (ggf. neu geladenen) Konverter zurueck."""
    settings.ensure_dirs()
    batch = limit or settings.max_articles_per_poll
    with make_http_client(settings) as client:
        if not skip_discover:
            discover(settings, store, client)
        if converter is None and _needs_pdf_converter(settings, store, batch):
            converter = PdfConverter(
                settings.docling_artifacts_path, settings.docling_threads
            )
        process_pending(settings, store, client, converter, batch)
    if settings.readwise_push:
        push_unpushed(settings, store)
    return converter
