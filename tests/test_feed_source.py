from medienpaed_reader.feed_source import parse_feed


def test_parse_feed_extracts_article_ids(feed_xml: bytes) -> None:
    entries = parse_feed(feed_xml)
    assert len(entries) == 20
    ids = [e.article_id for e in entries]
    assert len(ids) == len(set(ids))
    assert all(
        e.link.startswith("https://www.medienpaed.com/article/view/") for e in entries
    )
    assert all(e.title for e in entries)


def test_parse_feed_ignores_items_without_article_link() -> None:
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Ohne ID</title><link>https://example.org/news</link></item>
    <item><title>Mit ID</title><link>https://www.medienpaed.com/article/view/42</link></item>
    <item><title>Doppelt</title><link>https://www.medienpaed.com/article/view/42</link></item>
    </channel></rss>"""
    entries = parse_feed(xml)
    assert [e.article_id for e in entries] == [42]
