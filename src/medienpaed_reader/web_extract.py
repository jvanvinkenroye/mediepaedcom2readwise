"""Volltext eines Webartikels mit trafilatura aus der Seite loesen."""

import logging
import re
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

# heise (und aehnliche Seiten) kapseln Einbettungen in einen Consent-Platzhalter, der
# im Lesetext als "Empfohlener redaktioneller Inhalt ..." landet. Das eigentliche
# Ziel steckt im <noscript>-Fallback als iframe-src.
_OPT_IN_BLOCK = re.compile(r"<a-opt-in\b.*?</a-opt-in>", re.DOTALL | re.IGNORECASE)
_IFRAME_SRC = re.compile(r"<a?-?iframe\b[^>]*\bsrc=[\"']([^\"']+)", re.IGNORECASE)
_YOUTUBE_EMBED = re.compile(
    r"^(?:https?:)?//(?:www\.)?youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{6,})"
)
_CONSENT_TEXT = re.compile(
    r"<h\d>\s*Empfohlener redaktioneller Inhalt\s*</h\d>\s*"
    r"(?:<p>(?:(?!</p>).)*?(?:Zustimmung|einverstanden|Datenschutzerkl)(?:(?!</p>).)*</p>\s*){1,3}",
    re.DOTALL | re.IGNORECASE,
)


def _embed_link(src: str) -> str | None:
    """Aus einer iframe-Quelle einen fuer Leser brauchbaren Link machen."""
    match = _YOUTUBE_EMBED.match(src.strip())
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    if src.startswith(("http://", "https://", "//")):
        return src if "://" in src else f"https:{src}"
    return None


def replace_consent_embeds(page_html: str) -> str:
    """Consent-Platzhalter durch einen Link auf den eingebetteten Inhalt ersetzen.

    Ohne auffindbare Quelle (z. B. Preisvergleich-Widget) entfaellt der Block.
    """

    def _substitute(match: re.Match[str]) -> str:
        block = match.group(0)
        src = _IFRAME_SRC.search(block)
        link = _embed_link(src.group(1)) if src else None
        if not link:
            return ""
        label = "YouTube-Video" if "youtube.com" in link else "Eingebetteter Inhalt"
        return f'<p><a href="{link}">{label}: {link}</a></p>'

    return _OPT_IN_BLOCK.sub(_substitute, page_html)


def strip_consent_text(html: str) -> str:
    """Restliche Consent-Texte entfernen, falls der Platzhalter kein a-opt-in war."""
    return _CONSENT_TEXT.sub("", html)


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


def _extract_body_html(page_html: str, url: str) -> str:
    page_html = replace_consent_embeds(page_html)
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
    text = trafilatura.extract(page_html, url=url, output_format="txt", fast=True)
    text_len = len(text or "")
    if not body_html or text_len < MIN_TEXT_CHARS:
        raise ValueError(
            f"trafilatura fand keinen Artikeltext ({text_len} Zeichen) unter {url}"
        )
    return strip_consent_text(extract_body(body_html))


def _metadata(page_html: str, url: str, fallback_title: str) -> WebArticle:
    """Metadaten der Seite; der Text wird spaeter ergaenzt."""
    meta = trafilatura.extract_metadata(page_html, default_url=url)
    if meta is None:
        return WebArticle(title=fallback_title, html="")
    return WebArticle(
        title=meta.title or fallback_title,
        html="",
        authors=_split_authors(meta.author, meta.sitename),
        published=_parse_date(meta.date),
        description=meta.description,
        sitename=meta.sitename,
    )


def extract_article(page_html: str, url: str, fallback_title: str) -> WebArticle:
    """Lesetext und Metadaten aus dem HTML einer Artikelseite ziehen."""
    article = _metadata(page_html, url, fallback_title)
    article.html = _extract_body_html(page_html, url)
    return article


def fetch_article(client: httpx.Client, url: str, fallback_title: str) -> WebArticle:
    response = client.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
    response.raise_for_status()
    return extract_article(response.text, str(response.url), fallback_title)
