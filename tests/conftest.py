from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def article_html() -> str:
    return (FIXTURES / "article_2665.html").read_text(encoding="utf-8")


@pytest.fixture
def feed_xml() -> bytes:
    return (FIXTURES / "feed.xml").read_bytes()
