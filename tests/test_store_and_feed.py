import sqlite3
from pathlib import Path

from medienpaed_reader.feed_output import build_feed
from medienpaed_reader.sources import parse_sources
from medienpaed_reader.store import Store

SOURCES = parse_sources(
    """
    [medienpaed]
    name = "MedienPädagogik"
    feed_url = "https://www.medienpaed.com/rss"
    license = "CC BY 4.0"

    [ibis]
    name = "IBiS"
    feed_url = "https://www.informatischebildung.de/rss"
    """
)


def _store_with_article(tmp_path: Path) -> Store:
    store = Store(tmp_path / "db.sqlite")
    store.upsert_pending(
        "medienpaed", 1, "https://www.medienpaed.com/article/view/1", "Vorlaeufig"
    )
    store.mark_done(
        "medienpaed",
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
    store.upsert_pending("medienpaed", 2, "https://m/article/view/2", "Pending")
    # Gleiche ID bei anderer Quelle darf nicht kollidieren.
    store.upsert_pending("ibis", 1, "https://i/article/view/1", "IBiS 1")
    assert store.known_ids("medienpaed") == {1, 2}
    assert store.known_ids("ibis") == {1}
    assert [(r.source, r.article_id) for r in store.pending(10)] == [
        ("ibis", 1),
        ("medienpaed", 2),
    ]
    assert [r.article_id for r in store.done(10)] == [1]
    assert store.done(10, source="ibis") == []
    assert store.get("medienpaed", 1).authors == ["A. Autor", "B. Autorin"]

    store.mark_failed("medienpaed", 2, "boom", max_attempts=2)
    assert store.get("medienpaed", 2).status == "pending"
    store.mark_failed("medienpaed", 2, "boom", max_attempts=2)
    assert store.get("medienpaed", 2).status == "failed"
    assert store.reset("medienpaed", 2) is True
    assert store.get("medienpaed", 2).status == "pending"
    assert store.get("medienpaed", 2).attempts == 0
    assert store.reset("medienpaed", 999) is False

    assert [r.article_id for r in store.unpushed()] == [1]
    store.mark_pushed("medienpaed", 1)
    assert store.unpushed() == []
    assert ("medienpaed", "done", 1) in store.counts()

    store.mark_skipped("ibis", 1, "mark-known")
    assert store.get("ibis", 1).status == "skipped"
    assert store.pending(10) == [] or all(r.source != "ibis" for r in store.pending(10))
    assert ("ibis", "skipped", 1) in store.counts()


def test_migration_from_v1_schema(tmp_path: Path) -> None:
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE articles (
            article_id INTEGER PRIMARY KEY, landing_url TEXT NOT NULL,
            title TEXT NOT NULL, authors TEXT NOT NULL DEFAULT '[]',
            published TEXT, doi TEXT, language TEXT, abstract TEXT, pdf_url TEXT,
            html_path TEXT, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            readwise_pushed_at TEXT
        );
        INSERT INTO articles (article_id, landing_url, title, authors, status,
            html_path, created_at, updated_at, readwise_pushed_at)
        VALUES (2678, 'https://m/article/view/2678', 'Editorial', '["X"]', 'done',
            '/data/html/2678.html', '2026-09-08T00:00:00+00:00',
            '2026-09-08T00:00:00+00:00', '2026-09-08T01:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = Store(db)
    record = store.get("medienpaed", 2678)
    assert record is not None
    assert record.status == "done"
    assert record.html_path == "/data/html/2678.html"
    assert record.readwise_pushed_at is not None
    assert store.unpushed() == []
    # Zweiter Start darf nicht erneut migrieren.
    Store(db).get("medienpaed", 2678)


def test_build_feed_contains_fulltext_source_and_own_link(tmp_path: Path) -> None:
    store = _store_with_article(tmp_path)
    xml = build_feed(
        store.done(10),
        SOURCES,
        title="Test-Feed",
        public_base_url="https://reader.example.org/",
        feed_path="/feed/s.xml",
        load_html=lambda record: "<h1>Volltext</h1><p>Absatz</p>",
    ).decode()
    assert "<title>Test-Feed</title>" in xml
    assert "<title>Titel &amp; Test</title>" in xml
    assert "<link>https://reader.example.org/articles/medienpaed/1.html</link>" in xml
    assert "https://doi.org/10.21240/x" in xml
    assert "<content:encoded><![CDATA[<h1>Volltext</h1>" in xml
    assert "<dc:creator>A. Autor</dc:creator>" in xml
    assert "<pubDate>Mon, 20 Jul 2026" in xml
    assert "<category>MedienPädagogik</category>" in xml
