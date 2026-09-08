"""Quell-Feed von medienpaed.com lesen und Artikel-IDs extrahieren."""

import re
from dataclasses import dataclass

import feedparser
import httpx

ARTICLE_ID_RE = re.compile(r"/article/view/(\d+)")


@dataclass(frozen=True)
class FeedEntry:
    article_id: int
    link: str
    title: str


def parse_feed(xml: str | bytes) -> list[FeedEntry]:
    """Feed-XML in Eintraege umwandeln; Eintraege ohne Artikel-ID werden ignoriert."""
    parsed = feedparser.parse(xml)
    entries: list[FeedEntry] = []
    seen: set[int] = set()
    for entry in parsed.entries:
        link = entry.get("link", "")
        match = ARTICLE_ID_RE.search(link)
        if not match:
            continue
        article_id = int(match.group(1))
        if article_id in seen:
            continue
        seen.add(article_id)
        entries.append(
            FeedEntry(article_id=article_id, link=link, title=entry.get("title", ""))
        )
    return entries


def fetch_feed(client: httpx.Client, url: str) -> list[FeedEntry]:
    response = client.get(url)
    response.raise_for_status()
    return parse_feed(response.content)
