from pathlib import Path

import httpx
import respx

from medienpaed_reader import pipeline
from medienpaed_reader.config import Settings
from medienpaed_reader.readwise import (
    READWISE_DELETE_URL,
    READWISE_LIST_URL,
    READWISE_SAVE_URL,
)
from medienpaed_reader.store import Store


def _doc(doc_id: str, url: str, saved_using: str | None) -> dict:
    return {
        "id": doc_id,
        "source_url": url,
        "saved_using": saved_using,
        "title": doc_id,
    }


@respx.mock
def test_repush_deletes_only_own_doi_documents(tmp_path: Path) -> None:
    sources = tmp_path / "sources.toml"
    sources.write_text(
        '[medienpaed]\nname="M"\nfeed_url="https://m/rss"\n', encoding="utf-8"
    )
    settings = Settings(
        data_dir=tmp_path, sources_file=sources, readwise_token="t", readwise_push=True
    )
    settings.ensure_dirs()
    store = Store(settings.db_path)
    html = tmp_path / "1.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    store.upsert_pending("medienpaed", 1, "https://m/article/view/1", "T")
    store.mark_done(
        "medienpaed",
        1,
        title="T",
        authors=[],
        published=None,
        doi="10.1/x",
        language=None,
        abstract=None,
        pdf_url=None,
        html_path=str(html),
    )
    store.mark_pushed("medienpaed", 1)

    respx.get(READWISE_LIST_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    _doc("ours-doi", "https://doi.org/10.1/x", "medienpaed-reader"),
                    _doc("ours-ok", "https://m/article/view/2", "medienpaed-reader"),
                    _doc("foreign-doi", "https://doi.org/10.9/z", None),
                ],
                "nextPageCursor": None,
            },
        )
    )
    delete_route = respx.delete(READWISE_DELETE_URL.format(id="ours-doi")).mock(
        return_value=httpx.Response(204)
    )
    save_route = respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(201, json={"id": "new"})
    )

    pipeline.time.sleep = lambda _s: None  # type: ignore[assignment]
    deleted, pushed = pipeline.repush_doi_documents(settings, store)

    assert (deleted, pushed) == (1, 1)
    assert delete_route.called
    assert save_route.called
    assert store.get("medienpaed", 1).readwise_pushed_at is not None
