from pathlib import Path

import httpx
import respx

from medienpaed_reader import pipeline
from medienpaed_reader.config import Settings
from medienpaed_reader.readwise import READWISE_SAVE_URL
from medienpaed_reader.store import Store

FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Guter Artikel</title><link>https://w/news/gut</link></item>
<item><title>Nur Teaser</title><link>https://w/news/teaser</link></item>
</channel></rss>"""

PARAGRAPHS = "".join(
    f"<p>Absatz {i}: Ein ausreichend langer Satz ueber Fahrradnavigation mit E-Ink, "
    f"der genug Zeichen liefert, damit trafilatura ihn als Artikeltext erkennt {i}.</p>"
    for i in range(1, 6)
)
PAGE = f"""<html><head><title>Guter Artikel</title>
<meta name="author" content="Anna Autorin"></head>
<body><article><h1>Guter Artikel</h1>{PARAGRAPHS}</article></body></html>"""


@respx.mock
def test_run_once_with_web_source_converts_and_pushes(tmp_path: Path) -> None:
    sources = tmp_path / "sources.toml"
    sources.write_text(
        '[w]\ntype="web"\nname="W"\nfeed_url="https://w/rss"\n', encoding="utf-8"
    )
    settings = Settings(
        data_dir=tmp_path,
        sources_file=sources,
        readwise_push=True,
        readwise_token="t",
        max_attempts=1,
    )
    store = Store(settings.db_path)
    respx.get("https://w/rss").mock(return_value=httpx.Response(200, text=FEED))
    respx.get("https://w/news/gut").mock(return_value=httpx.Response(200, text=PAGE))
    respx.get("https://w/news/teaser").mock(
        return_value=httpx.Response(200, text="<html><body><p>Kurz.</p></body></html>")
    )
    save = respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(201, json={"id": "x"})
    )

    # Web-Quelle: kein PDF-Konverter noetig, run_once darf keinen laden.
    assert pipeline.run_once(settings, store) is None

    counts = dict(((s, st), n) for s, st, n in store.counts())
    assert counts == {("w", "done"): 1, ("w", "failed"): 1}
    good = store.done(10)[0]
    assert good.title == "Guter Artikel"
    assert good.authors == ["Anna Autorin"]
    assert Path(good.html_path).read_text(encoding="utf-8").count("<p>") >= 5
    assert good.readwise_pushed_at is not None
    assert save.call_count == 1

    failed = [
        r
        for r in (store.get("w", i) for i in store.known_ids("w"))
        if r is not None and r.status == "failed"
    ]
    assert len(failed) == 1
    assert "keinen Artikeltext" in (failed[0].last_error or "")
