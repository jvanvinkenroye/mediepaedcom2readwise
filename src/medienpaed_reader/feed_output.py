"""Eigenen RSS-2.0-Feed mit Volltext erzeugen."""

from collections.abc import Callable
from datetime import UTC, datetime, time

from feedgen.feed import FeedGenerator

from medienpaed_reader.store import ArticleRecord


def article_url(public_base_url: str, article_id: int) -> str:
    return f"{public_base_url.rstrip('/')}/articles/{article_id}.html"


def _pubdate(record: ArticleRecord) -> datetime:
    if record.published:
        try:
            day = datetime.strptime(record.published, "%Y-%m-%d").date()
            return datetime.combine(day, time(12, 0), tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromisoformat(record.created_at)


def _teaser(record: ArticleRecord) -> str:
    authors = ", ".join(record.authors)
    return f"{authors}: {record.title}" if authors else record.title


def build_feed(
    records: list[ArticleRecord],
    public_base_url: str,
    feed_path: str,
    load_html: Callable[[ArticleRecord], str],
) -> bytes:
    fg = FeedGenerator()
    fg.load_extension("dc")
    fg.id(f"{public_base_url.rstrip('/')}{feed_path}")
    fg.title("MedienPädagogik – Volltext")
    fg.link(href=f"{public_base_url.rstrip('/')}{feed_path}", rel="self")
    fg.link(href="https://www.medienpaed.com/", rel="alternate")
    fg.description(
        "Volltexte der Zeitschrift MedienPädagogik, automatisch aus den PDFs "
        "extrahiert. Lizenz der Beiträge: CC BY 4.0."
    )
    fg.language("de")

    for record in records:
        entry = fg.add_entry(order="append")
        entry.id(record.doi_url or record.landing_url)
        entry.guid(record.doi_url or record.landing_url, permalink=True)
        entry.title(record.title)
        entry.link(href=article_url(public_base_url, record.article_id))
        entry.published(_pubdate(record))
        if record.authors:
            entry.dc.dc_creator(record.authors)
        # feedgen legt content ohne description in <description> ab statt in
        # <content:encoded>; deshalb immer eine description setzen.
        entry.description(record.abstract or _teaser(record))
        html = load_html(record)
        if html:
            entry.content(html, type="CDATA")
    return fg.rss_str(pretty=True)
