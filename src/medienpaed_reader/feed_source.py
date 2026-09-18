"""Quell-Feeds lesen und Eintraege mit stabiler Kennung versehen."""

import hashlib
import re
from dataclasses import dataclass

import feedparser
import httpx

OJS_ARTICLE_ID_RE = re.compile(r"/article/view/(\d+)")


@dataclass(frozen=True)
class FeedEntry:
    article_id: int
    link: str
    title: str


def ojs_article_id(link: str) -> int | None:
    """Artikelnummer aus einem OJS-Link (/article/view/<ID>)."""
    match = OJS_ARTICLE_ID_RE.search(link)
    return int(match.group(1)) if match else None


def url_article_id(link: str) -> int | None:
    """Stabile Kennung fuer beliebige Artikel-URLs.

    Webartikel haben keine Nummer; 60 Bit des SHA-1 der URL passen in SQLites
    vorzeichenbehaftetes 64-Bit-INTEGER und sind fuer unsere Mengen kollisionsfrei.
    """
    link = link.strip()
    if not link:
        return None
    return int(hashlib.sha1(link.encode("utf-8")).hexdigest()[:15], 16)


def parse_feed(xml: str | bytes, source_type: str = "ojs") -> list[FeedEntry]:
    """Feed-XML in Eintraege umwandeln; Eintraege ohne brauchbaren Link entfallen."""
    id_from_link = ojs_article_id if source_type == "ojs" else url_article_id
    parsed = feedparser.parse(xml)
    entries: list[FeedEntry] = []
    seen: set[int] = set()
    for entry in parsed.entries:
        link = entry.get("link", "")
        article_id = id_from_link(link)
        if article_id is None or article_id in seen:
            continue
        seen.add(article_id)
        entries.append(
            FeedEntry(article_id=article_id, link=link, title=entry.get("title", ""))
        )
    return entries


def fetch_feed(
    client: httpx.Client, url: str, source_type: str = "ojs"
) -> list[FeedEntry]:
    response = client.get(url)
    response.raise_for_status()
    return parse_feed(response.content, source_type)
