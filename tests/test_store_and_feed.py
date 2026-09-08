from pathlib import Path

from medienpaed_reader.feed_output import build_feed
from medienpaed_reader.store import Store


def _store_with_article(tmp_path: Path) -> Store:
    store = Store(tmp_path / "db.sqlite")
    store.upsert_pending(1, "https://www.medienpaed.com/article/view/1", "Vorlaeufig")
    store.mark_done(
        1,
        title="Titel & Test",
        authors=["A. Autor", "B. Autorin"],
        published="2026-07-20",
        doi="10.21240/x",
        language="de",
        abstract="Kurz.",
        pdf_url="https://www.medienpaed.com/article/download/1/2",
        html_path=str(tmp_path / "1.html"),
    )
    return store


def test_store_lifecycle(tmp_path: Path) -> None:
    store = _store_with_article(tmp_path)
    store.upsert_pending(2, "https://www.medienpaed.com/article/view/2", "Pending")
    assert store.known_ids() == {1, 2}
    assert [r.article_id for r in store.pending(10)] == [2]
    assert [r.article_id for r in store.done(10)] == [1]
    assert store.get(1).authors == ["A. Autor", "B. Autorin"]

    store.mark_failed(2, "boom", max_attempts=2)
    assert store.get(2).status == "pending"
    store.mark_failed(2, "boom", max_attempts=2)
    assert store.get(2).status == "failed"

    assert [r.article_id for r in store.unpushed()] == [1]
    store.mark_pushed(1)
    assert store.unpushed() == []


def test_build_feed_contains_fulltext_and_own_link(tmp_path: Path) -> None:
    store = _store_with_article(tmp_path)
    xml = build_feed(
        store.done(10),
        "https://reader.example.org/",
        "/feed/s.xml",
        lambda record: "<h1>Volltext</h1><p>Absatz</p>",
    ).decode()
    assert "<title>Titel &amp; Test</title>" in xml
    assert "<link>https://reader.example.org/articles/1.html</link>" in xml
    assert "https://doi.org/10.21240/x" in xml
    assert "<content:encoded><![CDATA[<h1>Volltext</h1>" in xml
    assert "<dc:creator>A. Autor</dc:creator>" in xml
    assert "<pubDate>Mon, 20 Jul 2026" in xml
