from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from medienpaed_reader.article_page import choose_main_pdf, parse_article_page

LANDING = "https://www.medienpaed.com/article/view/2665"
PDF_HEADERS = {"content-type": "application/pdf"}


def test_parse_article_page_reads_citation_meta(article_html: str) -> None:
    meta = parse_article_page(2665, LANDING, article_html)
    assert meta.title.startswith("Didaktische Konzepte des Einsatzes digitaler Medien")
    assert meta.authors == ["Cornelia Dirks"]
    assert meta.published == date(2026, 7, 20)
    assert meta.doi == "10.21240/mpaed/diss.cd/2026.07.20.X"
    assert meta.doi_url == "https://doi.org/10.21240/mpaed/diss.cd/2026.07.20.X"
    assert meta.language == "de"
    assert meta.pdf_urls == [
        "https://www.medienpaed.com/article/download/2665/1623",
        "https://www.medienpaed.com/article/download/2665/1626",
    ]


def test_parse_article_page_without_meta_falls_back() -> None:
    meta = parse_article_page(7, LANDING, "<html><head></head><body/></html>")
    assert meta.title == "medienpaed Artikel 7"
    assert meta.pdf_urls == []
    assert meta.published is None


@pytest.mark.parametrize(
    ("sizes", "expected"),
    [
        ({"anhang": 1_000, "haupt": 9_000}, "haupt"),
        ({"haupt": 9_000, "anhang": 1_000}, "haupt"),
    ],
)
@respx.mock
def test_choose_main_pdf_keeps_largest_download(
    tmp_path: Path, sizes: dict[str, int], expected: str
) -> None:
    # Reihenfolge im Feed ist beliebig; ohne Content-Length entscheidet der Download.
    urls = {name: f"https://example.org/{name}.pdf" for name in sizes}
    for name, size in sizes.items():
        respx.get(urls[name]).mock(
            return_value=httpx.Response(
                200, content=b"%PDF" + b"x" * size, headers=PDF_HEADERS
            )
        )
    target = tmp_path / "pdf" / "2665.pdf"
    with httpx.Client() as client:
        chosen = choose_main_pdf(client, list(urls.values()), target)
    assert chosen == urls[expected]
    assert target.stat().st_size == sizes[expected] + 4
    assert sorted(p.name for p in target.parent.iterdir()) == ["2665.pdf"]


@respx.mock
def test_choose_main_pdf_skips_broken_candidates(tmp_path: Path) -> None:
    respx.get("https://example.org/a.pdf").mock(return_value=httpx.Response(404))
    respx.get("https://example.org/b.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-ok", headers=PDF_HEADERS)
    )
    target = tmp_path / "x.pdf"
    with httpx.Client() as client:
        assert (
            choose_main_pdf(
                client,
                ["https://example.org/a.pdf", "https://example.org/b.pdf"],
                target,
            )
            == "https://example.org/b.pdf"
        )
    assert target.read_bytes() == b"%PDF-ok"


@respx.mock
def test_choose_main_pdf_single_and_empty(tmp_path: Path) -> None:
    respx.get("https://example.org/x.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF", headers=PDF_HEADERS)
    )
    target = tmp_path / "x.pdf"
    with httpx.Client() as client:
        assert choose_main_pdf(client, [], target) is None
        assert choose_main_pdf(client, ["https://example.org/x.pdf"], target) == (
            "https://example.org/x.pdf"
        )
    assert target.exists()
