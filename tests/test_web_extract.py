import pytest

from medienpaed_reader.feed_source import parse_feed, url_article_id
from medienpaed_reader.web_extract import (
    extract_article,
    replace_consent_embeds,
    strip_consent_text,
)

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


OPT_IN_VIDEO = """<a-opt-in checkbox-text="YouTube-Video immer laden" type="Youtube">
<div><h2 class="opt-in__title">Empfohlener redaktioneller Inhalt</h2>
<p>Mit Ihrer Zustimmung wird hier ein externes YouTube-Video
(Google Ireland Limited) geladen.</p>
<button>YouTube-Video jetzt laden</button>
<p>Ich bin damit einverstanden, dass mir externe Inhalte angezeigt werden.</p></div>
<noscript><figure><a-iframe class="video__iframe" needs-consent
 src="//www.youtube-nocookie.com/embed/UIxUUwfWhVo"
 title="YouTube video player"></a-iframe>
</figure></noscript></a-opt-in>"""

OPT_IN_WIDGET = """<a-opt-in type="Preisvergleich">
<h2>Empfohlener redaktioneller Inhalt</h2>
<p>Mit Ihrer Zustimmung wird hier ein externer Preisvergleich geladen.</p></a-opt-in>"""


def test_replace_consent_embeds_links_video_and_drops_widgets() -> None:
    html = f"<p>Vorher</p>{OPT_IN_VIDEO}<p>Mitte</p>{OPT_IN_WIDGET}<p>Nachher</p>"
    result = replace_consent_embeds(html)
    assert "Empfohlener redaktioneller Inhalt" not in result
    assert 'href="https://www.youtube.com/watch?v=UIxUUwfWhVo"' in result
    assert result.index("Vorher") < result.index("youtube.com") < result.index("Mitte")
    assert result.endswith("<p>Nachher</p>")


def test_extract_article_keeps_video_link_in_place() -> None:
    page = PAGE.replace("</article>", f"{OPT_IN_VIDEO}<p>Schluss.</p></article>")
    article = extract_article(page, "https://example.org/news/1", "F")
    assert "Empfohlener redaktioneller Inhalt" not in article.html
    assert "einverstanden" not in article.html
    assert "https://www.youtube.com/watch?v=UIxUUwfWhVo" in article.html
    assert article.html.index("youtube.com") < article.html.index("Schluss.")


def test_strip_consent_text_removes_leftover_block() -> None:
    html = (
        "<p>A</p><h2>Empfohlener redaktioneller Inhalt</h2>"
        "<p>Mit Ihrer Zustimmung wird hier ein externer Preisvergleich geladen.</p>"
        "<p>Ich bin damit einverstanden, dass mir externe Inhalte angezeigt werden. "
        "Mehr dazu in unserer <a href='x'>Datenschutzerklärung</a>.</p><p>B</p>"
    )
    assert strip_consent_text(html) == "<p>A</p><p>B</p>"
