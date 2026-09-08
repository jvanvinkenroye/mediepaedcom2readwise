from datetime import date

import httpx
import pytest
import respx

from medienpaed_reader.article_page import choose_main_pdf, parse_article_page

LANDING = "https://www.medienpaed.com/article/view/2665"


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
        ({"a": 1000, "b": 9_000_000}, "b"),
        ({"a": 9_000_000, "b": 1000}, "a"),
        ({"a": 0, "b": 0}, "a"),
    ],
)
@respx.mock
def test_choose_main_pdf_prefers_largest(sizes: dict[str, int], expected: str) -> None:
    urls = {name: f"https://example.org/{name}.pdf" for name in sizes}
    for name, size in sizes.items():
        respx.head(urls[name]).mock(
            return_value=httpx.Response(200, headers={"content-length": str(size)})
        )
    with httpx.Client() as client:
        assert choose_main_pdf(client, list(urls.values())) == urls[expected]


def test_choose_main_pdf_single_and_empty() -> None:
    with httpx.Client() as client:
        assert choose_main_pdf(client, []) is None
        assert choose_main_pdf(client, ["x"]) == "x"
