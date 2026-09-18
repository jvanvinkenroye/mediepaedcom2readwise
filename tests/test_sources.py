from pathlib import Path

import pytest

from medienpaed_reader.sources import DEFAULT_SOURCES_TOML, load_sources, parse_sources

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_sources_contains_medienpaed() -> None:
    sources = parse_sources(DEFAULT_SOURCES_TOML)
    assert list(sources) == ["medienpaed"]
    assert sources["medienpaed"].tags == ["medienpaed"]
    assert sources["medienpaed"].feed_url.startswith("https://www.medienpaed.com/")


def test_repo_sources_toml_is_valid() -> None:
    sources = load_sources(REPO_ROOT / "sources.toml")
    assert {"medienpaed", "ibis"} <= set(sources)
    assert sources["ibis"].license == "CC BY-NC 4.0"


def test_missing_file_falls_back_to_default(tmp_path: Path) -> None:
    assert list(load_sources(tmp_path / "nope.toml")) == ["medienpaed"]


def test_disabled_source_is_skipped_and_tags_override() -> None:
    sources = parse_sources(
        """
        [a]
        name = "A"
        feed_url = "https://a.example/rss"
        readwise_tags = ["x", "y"]

        [b]
        name = "B"
        feed_url = "https://b.example/rss"
        enabled = false
        """
    )
    assert list(sources) == ["a"]
    assert sources["a"].tags == ["x", "y"]


@pytest.mark.parametrize("bad", ["", "[a b]\nname='x'\nfeed_url='u'", "[a]\nname='x'"])
def test_invalid_sources_raise(bad: str) -> None:
    with pytest.raises(Exception):  # noqa: B017 - tomllib/pydantic/ValueError
        parse_sources(bad)


def test_key_with_slash_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_sources('["a/b"]\nname = "x"\nfeed_url = "u"')
