import pytest

from medienpaed_reader.feed_source import parse_feed, url_article_id
from medienpaed_reader.web_extract import extract_article

# trafilatura entfernt wiederholte Absaetze, deshalb vier verschiedene.
PARAGRAPHS = "".join(
    f"<p>Absatz {i}: Radfahrer kennen das Problem mit dem Smartphone am Lenker, "
    "das bei Sonnenschein kaum ablesbar ist. Ein E-Paper-Display verbessert die "
    f"Lesbarkeit bei Sonnenlicht sogar, braucht aber Firmware Nummer {i}.</p>"
    for i in range(1, 5)
)

PAGE = f"""<!doctype html><html lang="de"><head>
<title>Offline-Karten auf E-Ink | Beispielseite</title>
<meta property="og:title" content="Offline-Karten auf E-Ink: Fahrradnavi">
<meta name="author" content="Marcus Hansson">
<meta property="article:published_time" content="2026-09-07T10:00:00+02:00">
<meta name="description" content="Eine GPS-Karte am Lenker fuer 90 Euro.">
<meta property="og:site_name" content="Beispielseite">
</head><body>
<nav><a href="/">Start</a><a href="/news">News</a><a href="/forum">Forum</a></nav>
<article>
<h1>Offline-Karten auf E-Ink: Fahrradnavi</h1>
{PARAGRAPHS}
<p>Mehr dazu im <a href="https://opentrailpaper.com/">Projekt</a>.</p>
</article>
<footer><p>Impressum · Datenschutz · Newsletter abonnieren</p></footer>
</body></html>"""


def test_extract_article_returns_body_and_metadata() -> None:
    article = extract_article(PAGE, "https://example.org/news/1", "Fallback")
    assert article.title.startswith("Offline-Karten auf E-Ink")
    assert article.authors == ["Marcus Hansson"]
    assert str(article.published) == "2026-09-07"
    assert article.description == "Eine GPS-Karte am Lenker fuer 90 Euro."
    assert "Radfahrer kennen das Problem" in article.html
    assert 'href="https://opentrailpaper.com/"' in article.html
    assert "Impressum" not in article.html
    assert "<html" not in article.html and "<body" not in article.html


def test_extract_article_rejects_teaser_only_pages() -> None:
    teaser = (
        "<html><body><article><p>Nur ein kurzer Anriss.</p></article></body></html>"
    )
    with pytest.raises(ValueError, match="keinen Artikeltext"):
        extract_article(teaser, "https://example.org/x", "T")


def test_url_article_id_is_stable_and_fits_sqlite_integer() -> None:
    a = url_article_id("https://example.org/a")
    assert a == url_article_id("https://example.org/a ")
    assert a != url_article_id("https://example.org/b")
    assert a is not None and 0 < a < 2**63
    assert url_article_id("") is None


def test_parse_feed_web_type_uses_url_ids() -> None:
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>A</title><link>https://example.org/news/a</link></item>
    <item><title>B</title><link>https://example.org/news/b</link></item>
    <item><title>A nochmal</title><link>https://example.org/news/a</link></item>
    </channel></rss>"""
    entries = parse_feed(xml, "web")
    assert [e.title for e in entries] == ["A", "B"]
    assert entries[0].article_id == url_article_id("https://example.org/news/a")
    # Als OJS-Quelle gelesen liefert der Feed nichts: keine /article/view/-IDs.
    assert parse_feed(xml, "ojs") == []
