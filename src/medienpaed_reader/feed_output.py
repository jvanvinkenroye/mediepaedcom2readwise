"""Eigenen RSS-2.0-Feed mit Volltext erzeugen."""

from collections.abc import Callable
from datetime import UTC, datetime, time

from feedgen.feed import FeedGenerator

from medienpaed_reader.sources import Source
from medienpaed_reader.store import ArticleRecord


def article_url(public_base_url: str, record: ArticleRecord) -> str:
    base = public_base_url.rstrip("/")
    return f"{base}/articles/{record.source}/{record.article_id}.html"


def _pubdate(record: ArticleRecord) -> datetime:
    if record.published:
        try:
            day = datetime.strptime(record.published, "%Y-%m-%d").date()
            return datetime.combine(day, time(12, 0), tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromisoformat(record.created_at)


def _teaser(record: ArticleRecord, source: Source | None) -> str:
    authors = ", ".join(record.authors)
    head = f"{authors}: {record.title}" if authors else record.title
    return f"{head} ({source.name})" if source else head


def build_feed(
    records: list[ArticleRecord],
    sources: dict[str, Source],
    *,
    title: str,
    public_base_url: str,
    feed_path: str,
    load_html: Callable[[ArticleRecord], str],
    homepage: str = "",
) -> bytes:
    base = public_base_url.rstrip("/")
    fg = FeedGenerator()
    fg.load_extension("dc")
    fg.id(f"{base}{feed_path}")
    fg.title(title)
    fg.link(href=f"{base}{feed_path}", rel="self")
    fg.link(href=homepage or base, rel="alternate")
    names = ", ".join(s.name for s in sources.values())
    fg.description(
        f"Volltexte aus {names}, automatisch aus den PDFs extrahiert. "
        "Lizenz siehe jeweiliger Beitrag."
    )
    fg.language("de")

    for record in records:
        source = sources.get(record.source)
        entry = fg.add_entry(order="append")
        entry.id(record.doi_url or record.landing_url)
        entry.guid(record.doi_url or record.landing_url, permalink=True)
        entry.title(record.title)
        entry.link(href=article_url(public_base_url, record))
        entry.published(_pubdate(record))
        if record.authors:
            entry.dc.dc_creator(record.authors)
        if source:
            entry.category(term=source.key, label=source.name)
        # feedgen legt content ohne description in <description> ab statt in
        # <content:encoded>; deshalb immer eine description setzen.
        entry.description(record.abstract or _teaser(record, source))
        html = load_html(record)
        if html:
            entry.content(html, type="CDATA")
    return fg.rss_str(pretty=True)
