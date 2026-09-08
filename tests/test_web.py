from pathlib import Path

from medienpaed_reader.config import Settings
from medienpaed_reader.store import Store
from medienpaed_reader.web import create_app


def test_web_routes(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path, feed_secret="s3cret", public_base_url="http://h"
    )
    settings.ensure_dirs()
    html_file = settings.html_dir / "5.html"
    html_file.write_text("<h2>Kapitel</h2><p>Text</p>", encoding="utf-8")
    store = Store(settings.db_path)
    store.upsert_pending(5, "https://www.medienpaed.com/article/view/5", "x")
    store.mark_done(
        5,
        title="Fuenf",
        authors=["Z"],
        published="2026-01-02",
        doi=None,
        language="de",
        abstract=None,
        pdf_url="https://www.medienpaed.com/article/download/5/6",
        html_path=str(html_file),
    )
    client = create_app(settings, store).test_client()

    assert client.get("/healthz").data == b"ok"
    assert client.get("/feed/wrong.xml").status_code == 404
    feed = client.get("/feed/s3cret.xml")
    assert feed.status_code == 200
    assert b"<content:encoded><![CDATA[<h2>Kapitel</h2>" in feed.data
    assert b"<link>http://h/articles/5.html</link>" in feed.data

    page = client.get("/articles/5.html")
    assert page.status_code == 200
    assert b"<h1>Fuenf</h1>" in page.data
    assert b"<h2>Kapitel</h2>" in page.data
    assert b'href="https://www.medienpaed.com/article/download/5/6"' in page.data
    assert client.get("/articles/999.html").status_code == 404
