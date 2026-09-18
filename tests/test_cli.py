from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from medienpaed_reader import poller
from medienpaed_reader.cli import app
from medienpaed_reader.readwise import READWISE_SAVE_URL
from medienpaed_reader.store import Store

runner = CliRunner()

FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Eins</title><link>https://m/article/view/1</link></item>
<item><title>Zwei</title><link>https://m/article/view/2</link></item>
</channel></rss>"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sources = tmp_path / "sources.toml"
    sources.write_text(
        '[m]\nname="M"\nfeed_url="https://m/rss"\nlicense="CC BY 4.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SOURCES_FILE", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("READWISE_TOKEN", "t")
    monkeypatch.delenv("READWISE_PUSH", raising=False)
    return tmp_path


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run-once", "serve", "sources", "reset", "readwise-repush"):
        assert command in result.output


@respx.mock
def test_mark_known_then_sources(env: Path) -> None:
    respx.get("https://m/rss").mock(return_value=httpx.Response(200, text=FEED))
    result = runner.invoke(app, ["mark-known", "-q"])
    assert result.exit_code == 0, result.output
    store = Store(env / "articles.sqlite")
    assert {r.status for r in [store.get("m", 1), store.get("m", 2)]} == {"skipped"}

    result = runner.invoke(app, ["sources", "-q"])
    assert result.exit_code == 0
    assert "m: M <https://m/rss>" in result.output
    assert "skipped: 2" in result.output


def test_reset_marks_pending_and_wakes_poller(env: Path) -> None:
    store = Store(env / "articles.sqlite")
    store.upsert_pending("m", 5, "https://m/article/view/5", "T")
    store.mark_failed("m", 5, "boom", max_attempts=1)
    store.close()

    result = runner.invoke(app, ["reset", "m", "5", "-q"])
    assert result.exit_code == 0, result.output
    assert "pending" in result.output
    assert Store(env / "articles.sqlite").get("m", 5).status == "pending"
    assert (env / poller.WAKE_FILE).exists()


def test_reset_unknown_article_fails(env: Path) -> None:
    result = runner.invoke(app, ["reset", "m", "999", "-q"])
    assert result.exit_code == 1


@respx.mock
def test_push_readwise_dry_run_sends_nothing(env: Path) -> None:
    route = respx.post(READWISE_SAVE_URL)
    html = env / "5.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    store = Store(env / "articles.sqlite")
    store.upsert_pending("m", 5, "https://m/article/view/5", "T")
    store.mark_done(
        "m",
        5,
        title="T",
        authors=[],
        published=None,
        doi=None,
        language=None,
        abstract=None,
        pdf_url=None,
        html_path=str(html),
    )
    store.close()

    result = runner.invoke(app, ["push-readwise", "--dry-run", "-q"])
    assert result.exit_code == 0, result.output
    assert "0 Artikel gepusht." in result.output
    assert not route.called
