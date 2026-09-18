"""Integrationstest mit echtem docling. Laeuft nur mit `uv run pytest -m slow`."""

from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "editorial_2678.pdf"


@pytest.mark.slow
def test_docling_converts_editorial_pdf(tmp_path: Path) -> None:
    from medienpaed_reader.pdf_convert import PdfConverter

    converter = PdfConverter(num_threads=4)
    html_out = tmp_path / "2678.html"
    md_out = tmp_path / "2678.md"
    body = converter.convert(FIXTURE, html_out, md_out)

    assert html_out.exists() and md_out.exists()
    assert len(body) > 20_000
    assert "<h2>" in body
    assert "Zusammenfassung" in body
    assert "Kommunikation ist Ausgangspunkt" in body
    # Bereinigung: keine leeren Absaetze, keine Icon-Font-Zeichen
    assert "<p></p>" not in body
    assert not any("" <= ch <= "" for ch in body)
