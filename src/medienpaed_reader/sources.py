"""Quellen (OJS-Zeitschriften) aus sources.toml laden."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

DEFAULT_SOURCES_TOML = """\
# Eine Tabelle pro Quelle. Der Schluessel (z. B. "medienpaed") ist stabil und
# landet in Datenbank, Dateinamen und als Readwise-Tag.
# type = "ojs" (Default, PDF + docling) oder "web" (Artikelseite + trafilatura).

[medienpaed]
name = "MedienPädagogik"
feed_url = "https://www.medienpaed.com/gateway/plugin/WebFeedGatewayPlugin/rss2"
homepage = "https://www.medienpaed.com/"
license = "CC BY 4.0"
"""


SOURCE_TYPES = ("ojs", "web")


class Source(BaseModel):
    key: str
    name: str
    feed_url: str
    # "ojs": PDF ueber citation_pdf_url + docling; "web": Artikelseite + trafilatura
    type: str = "ojs"
    homepage: str = ""
    license: str = ""
    readwise_tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key_is_slug(cls, value: str) -> str:
        # Der Schluessel wird zum Verzeichnisnamen und URL-Bestandteil.
        if not value or not all(c.isalnum() or c in "-_" for c in value):
            raise ValueError(f"Ungueltiger Quellen-Schluessel: {value!r}")
        return value

    @field_validator("type")
    @classmethod
    def _type_known(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(
                f"Unbekannter Quellentyp {value!r}, erlaubt: {SOURCE_TYPES}"
            )
        return value

    @property
    def tags(self) -> list[str]:
        return self.readwise_tags or [self.key]


def parse_sources(toml_text: str) -> dict[str, Source]:
    data = tomllib.loads(toml_text)
    sources: dict[str, Source] = {}
    for key, table in data.items():
        if not isinstance(table, dict):
            raise ValueError(f"Quelle {key!r} muss eine Tabelle sein")
        source = Source(key=key, **table)
        if source.enabled:
            sources[key] = source
    if not sources:
        raise ValueError("sources.toml enthaelt keine aktive Quelle")
    return sources


def load_sources(path: Path) -> dict[str, Source]:
    """sources.toml lesen; fehlt die Datei, gilt die medienpaed-Voreinstellung."""
    text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_SOURCES_TOML
    return parse_sources(text)
