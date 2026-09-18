"""Metadaten und PDF-Link aus der OJS-Artikelseite (citation_* Meta-Tags) lesen."""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)


@dataclass
class ArticleMeta:
    article_id: int
    landing_url: str
    title: str
    authors: list[str] = field(default_factory=list)
    published: date | None = None
    doi: str | None = None
    language: str | None = None
    abstract: str | None = None
    pdf_urls: list[str] = field(default_factory=list)

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None


def _meta_values(tree: HTMLParser, name: str) -> list[str]:
    values = []
    for node in tree.css(f'meta[name="{name}"]'):
        content = node.attributes.get("content")
        if content:
            values.append(content.strip())
    return values


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for sep in ("/", "-"):
        parts = raw.split(sep)
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            try:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                return None
    return None


def parse_article_page(article_id: int, landing_url: str, html: str) -> ArticleMeta:
    tree = HTMLParser(html)
    titles = _meta_values(tree, "citation_title")
    abstracts = _meta_values(tree, "DC.Description") or _meta_values(
        tree, "description"
    )
    return ArticleMeta(
        article_id=article_id,
        landing_url=landing_url,
        title=titles[0] if titles else f"medienpaed Artikel {article_id}",
        authors=_meta_values(tree, "citation_author"),
        published=_parse_date(next(iter(_meta_values(tree, "citation_date")), None)),
        doi=next(iter(_meta_values(tree, "citation_doi")), None),
        language=next(iter(_meta_values(tree, "citation_language")), None),
        abstract=abstracts[0] if abstracts else None,
        pdf_urls=_meta_values(tree, "citation_pdf_url"),
    )


def fetch_article_meta(
    client: httpx.Client, article_id: int, landing_url: str
) -> ArticleMeta:
    response = client.get(landing_url)
    response.raise_for_status()
    return parse_article_page(article_id, str(response.url), response.text)


def choose_main_pdf(
    client: httpx.Client, pdf_urls: list[str], target_path: Path
) -> str | None:
    """Alle PDF-Galleys laden und die groesste Datei als Haupttext behalten.

    OJS listet Anhaenge ebenfalls als citation_pdf_url, in beliebiger Reihenfolge.
    HEAD-Anfragen liefern bei medienpaed.com keine Content-Length, deshalb entscheidet
    die tatsaechliche Dateigroesse nach dem Download. Anhaenge sind klein, der
    Mehraufwand ist gering. Das gewaehlte PDF liegt danach unter target_path.
    """
    if not pdf_urls:
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if len(pdf_urls) == 1:
        download_pdf(client, pdf_urls[0], str(target_path))
        return pdf_urls[0]

    candidates: list[tuple[int, str, Path]] = []
    for index, url in enumerate(pdf_urls):
        candidate = target_path.with_suffix(f".{index}.pdf")
        try:
            download_pdf(client, url, str(candidate))
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("PDF-Kandidat %s nicht ladbar: %s", url, exc)
            candidate.unlink(missing_ok=True)
            continue
        candidates.append((candidate.stat().st_size, url, candidate))
    if not candidates:
        raise ValueError("Keines der PDF-Galleys war ladbar")

    candidates.sort(reverse=True)
    _, best_url, best_path = candidates[0]
    best_path.replace(target_path)
    for _, _, other in candidates[1:]:
        other.unlink(missing_ok=True)
    return best_url


def download_pdf(client: httpx.Client, url: str, target_path: str) -> None:
    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and "octet-stream" not in content_type:
            raise ValueError(f"Kein PDF unter {url}: content-type={content_type}")
        with open(target_path, "wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
