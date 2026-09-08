"""PDF mit docling in HTML umwandeln (CPU, ohne OCR) und Artefakte bereinigen."""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Blocksatz-PDFs hinterlassen typische Artefakte: getrennte Woerter am Zeilenende,
# doppelte Leerzeichen, alleinstehende Seitenzahlen.
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*([a-zäöüß])")
_HYPHEN_SPACE = re.compile(r"(\w) -([a-zäöüß])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_PAGE_NUMBER_PARA = re.compile(r"<p>\s*\d{1,4}\s*</p>")
_EMPTY_PARA = re.compile(r"<p>\s*</p>")
# Icon-Fonts (ORCID, Mail) landen als Private-Use-Zeichen im Text.
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")


def clean_html(html: str) -> str:
    html = _HYPHEN_BREAK.sub(r"\1\2", html)
    html = _HYPHEN_SPACE.sub(r"\1\2", html)
    html = _MULTI_SPACE.sub(" ", html)
    html = _PRIVATE_USE.sub("", html)
    html = _PAGE_NUMBER_PARA.sub("", html)
    html = _EMPTY_PARA.sub("", html)
    return html


def extract_body(html: str) -> str:
    """docling liefert ein komplettes Dokument; wir brauchen nur den Body-Inhalt."""
    match = re.search(r"<body[^>]*>(.*)</body>", html, flags=re.DOTALL | re.IGNORECASE)
    body = match.group(1) if match else html
    # docling setzt eigene Styles und ein Wrapper-div; beides ist fuer Reader Ballast.
    body = re.sub(r"<style.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    return body.strip()


class PdfConverter:
    def __init__(
        self, artifacts_path: Path | None = None, num_threads: int = 4
    ) -> None:
        # Import erst hier: docling zieht torch, das dauert und stoert Tests/CLI-Help.
        from docling.datamodel.accelerator_options import (
            AcceleratorDevice,
            AcceleratorOptions,
        )
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = True
        options.generate_picture_images = False
        options.accelerator_options = AcceleratorOptions(
            num_threads=num_threads, device=AcceleratorDevice.CPU
        )
        if artifacts_path is not None:
            options.artifacts_path = str(artifacts_path)

        self._converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def convert(
        self, pdf_path: Path, html_out: Path, md_out: Path | None = None
    ) -> str:
        """PDF konvertieren, bereinigtes Body-HTML speichern und zurueckgeben."""
        from docling_core.types.doc.base import ImageRefMode

        log.info("docling: konvertiere %s", pdf_path)
        result = self._converter.convert(str(pdf_path))
        document = result.document
        raw_html = document.export_to_html(image_mode=ImageRefMode.PLACEHOLDER)
        body = clean_html(extract_body(raw_html))
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(body, encoding="utf-8")
        if md_out is not None:
            md_out.write_text(document.export_to_markdown(), encoding="utf-8")
        log.info("docling: fertig, %d Zeichen HTML", len(body))
        return body
