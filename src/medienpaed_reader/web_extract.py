"""Volltext eines Webartikels mit trafilatura aus der Seite loesen."""

import logging
from dataclasses import dataclass, field
from datetime import date

import httpx
import trafilatura

from medienpaed_reader.pdf_convert import extract_body

log = logging.getLogger(__name__)

# Ein paar Seiten liefern Bots nur den Teaser; ein Browser-Kennung hilft meist.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
MIN_TEXT_CHARS = 300


@dataclass
class WebArticle:
    title: str
    html: str
    authors: list[str] = field(default_factory=list)
    published: date | None = None
    language: str | None = None
    description: str | None = None
    sitename: str | None = None


def _split_authors(raw: str | None, sitename: str | None) -> list[str]:
    """Autorenfeld aufteilen; den Seitennamen (z. B. "Heise Online") aussortieren."""
    if not raw:
        return []
    site = (sitename or "").strip().lower()
    return [
        a.strip()
        for a in raw.replace(",", ";").split(";")
        if a.strip() and a.strip().lower() != site
    ]


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def extract_article(page_html: str, url: str, fallback_title: str) -> WebArticle:
    """Lesetext und Metadaten aus dem HTML einer Artikelseite ziehen."""
    body_html = trafilatura.extract(
        page_html,
        url=url,
        output_format="html",
        include_links=True,
        include_tables=True,
        include_formatting=True,
        include_images=False,
        include_comments=False,
        favor_recall=True,
    )
    text_len = len(
        trafilatura.extract(page_html, url=url, output_format="txt", fast=True) or ""
    )
    if not body_html or text_len < MIN_TEXT_CHARS:
        raise ValueError(
            f"trafilatura fand keinen Artikeltext ({text_len} Zeichen) unter {url}"
        )
    meta = trafilatura.extract_metadata(page_html, default_url=url)
    title = (meta.title if meta and meta.title else None) or fallback_title
    return WebArticle(
        title=title,
        html=extract_body(body_html),
        authors=_split_authors(
            meta.author if meta else None, meta.sitename if meta else None
        ),
        published=_parse_date(meta.date if meta else None),
        language=None,
        description=meta.description if meta else None,
        sitename=meta.sitename if meta else None,
    )


def fetch_article(client: httpx.Client, url: str, fallback_title: str) -> WebArticle:
    response = client.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
    response.raise_for_status()
    return extract_article(response.text, str(response.url), fallback_title)
