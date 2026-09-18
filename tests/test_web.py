from pathlib import Path

from medienpaed_reader.config import Settings
from medienpaed_reader.store import Store
from medienpaed_reader.web import create_app

SOURCES_TOML = """
[medienpaed]
name = "MedienPädagogik"
feed_url = "https://www.medienpaed.com/rss"
homepage = "https://www.medienpaed.com/"
license = "CC BY 4.0"

[ibis]
name = "IBiS"
feed_url = "https://www.informatischebildung.de/rss"
license = "CC BY-NC 4.0"
"""


def _add_done(store: Store, html_dir: Path, source: str, article_id: int) -> None:
    html_file = html_dir / source / f"{article_id}.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(f"<h2>Kapitel {source}</h2><p>Text</p>", encoding="utf-8")
    store.upsert_pending(source, article_id, f"https://{source}/article/view/5", "x")
    store.mark_done(
        source,
        article_id,
        title=f"Titel {source}",
        authors=["Z"],
        published="2026-01-02",
        doi=None,
        language="de",
        abstract=None,
        pdf_url=f"https://{source}/article/download/5/6",
        html_path=str(html_file),
    )


def test_web_routes(tmp_path: Path) -> None:
    sources_file = tmp_path / "sources.toml"
    sources_file.write_text(SOURCES_TOML, encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path,
        sources_file=sources_file,
        feed_secret="s3cret",
        public_base_url="http://h",
        feed_title="Alle",
    )
    settings.ensure_dirs()
    store = Store(settings.db_path)
    _add_done(store, settings.html_dir, "medienpaed", 5)
    _add_done(store, settings.html_dir, "ibis", 5)
    client = create_app(settings, store).test_client()

    assert client.get("/healthz").data == b"ok"
    assert client.get("/feed/wrong.xml").status_code == 404
    assert client.get("/feed/s3cret/unknown.xml").status_code == 404

    feed = client.get("/feed/s3cret.xml")
    assert feed.status_code == 200
    assert feed.data.count(b"<item>") == 2
    assert b"<title>Alle</title>" in feed.data
    assert b"<link>http://h/articles/medienpaed/5.html</link>" in feed.data
    assert b"<link>http://h/articles/ibis/5.html</link>" in feed.data
    # Kopfzeile mit Quelle und Lizenz steht im Volltext.
    assert "MedienPädagogik, CC BY 4.0".encode() in feed.data
    assert b"IBiS, CC BY-NC 4.0" in feed.data

    ibis_feed = client.get("/feed/s3cret/ibis.xml")
    assert ibis_feed.status_code == 200
    assert ibis_feed.data.count(b"<item>") == 1
    assert "<title>IBiS – Volltext</title>".encode() in ibis_feed.data

    page = client.get("/articles/ibis/5.html")
    assert page.status_code == 200
    assert b"<h1>Titel ibis</h1>" in page.data
    assert b"<h2>Kapitel ibis</h2>" in page.data
    assert b"IBiS, CC BY-NC 4.0" in page.data
    assert client.get("/articles/medienpaed/999.html").status_code == 404
    assert client.get("/articles/nope/5.html").status_code == 404
