from pathlib import Path

import httpx
import respx

from medienpaed_reader import readwise_sync
from medienpaed_reader.config import Settings
from medienpaed_reader.readwise import READWISE_SAVE_URL
from medienpaed_reader.store import Store


def _settings(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources.toml"
    sources.write_text('[m]\nname="M"\nfeed_url="https://m/rss"\n', encoding="utf-8")
    settings = Settings(data_dir=tmp_path, sources_file=sources, readwise_token="t")
    settings.ensure_dirs()
    return settings


def _add_done(store: Store, tmp_path: Path, article_id: int) -> None:
    html = tmp_path / f"{article_id}.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    store.upsert_pending("m", article_id, f"https://m/article/view/{article_id}", "T")
    store.mark_done(
        "m",
        article_id,
        title=f"T{article_id}",
        authors=[],
        published=None,
        doi=None,
        language=None,
        abstract=None,
        pdf_url=None,
        html_path=str(html),
    )


@respx.mock
def test_failed_push_does_not_block_following_articles(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    for article_id in (1, 2, 3):
        _add_done(store, tmp_path, article_id)

    responses = iter(
        [
            httpx.Response(500, text="kaputt"),
            httpx.Response(201, json={"id": "b"}),
            httpx.Response(201, json={"id": "c"}),
        ]
    )
    respx.post(READWISE_SAVE_URL).mock(side_effect=lambda request: next(responses))

    assert readwise_sync.push_unpushed(settings, store) == 2
    assert [r.article_id for r in store.unpushed()] == [1]


@respx.mock
def test_rate_limit_stops_batch_but_keeps_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    for article_id in (1, 2):
        _add_done(store, tmp_path, article_id)
    route = respx.post(READWISE_SAVE_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    assert readwise_sync.push_unpushed(settings, store) == 0
    assert route.call_count == 1
    assert len(store.unpushed()) == 2
