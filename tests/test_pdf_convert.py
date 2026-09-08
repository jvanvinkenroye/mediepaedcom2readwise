from medienpaed_reader.pdf_convert import clean_html, extract_body


def test_extract_body_strips_document_wrapper() -> None:
    html = (
        "<html><head><title>x</title></head>"
        "<body><style>p{}</style><p>Hi</p></body></html>"
    )
    assert extract_body(html) == "<p>Hi</p>"


def test_clean_html_joins_hyphenated_words() -> None:
    assert clean_html("<p>Medien-\npädagogik</p>") == "<p>Medienpädagogik</p>"
    assert clean_html("<p>Bild -ung</p>") == "<p>Bildung</p>"


def test_clean_html_keeps_real_compound_hyphens() -> None:
    # Bindestrich vor Grossbuchstabe ist ein echter Bindestrich, kein Umbruch.
    assert clean_html("<p>Video-Stimulated</p>") == "<p>Video-Stimulated</p>"


def test_clean_html_drops_page_numbers_and_empty_paragraphs() -> None:
    assert (
        clean_html("<p>Text</p><p>17</p><p> </p><p>Mehr</p>")
        == "<p>Text</p><p>Mehr</p>"
    )


def test_clean_html_removes_icon_font_glyphs() -> None:
    assert clean_html("<p>\uf25e</p><p>Name \uf4e7</p>") == "<p>Name </p>"
