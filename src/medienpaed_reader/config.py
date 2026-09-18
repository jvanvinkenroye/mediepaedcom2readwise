"""Laufzeitkonfiguration aus Umgebungsvariablen."""

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from medienpaed_reader.sources import Source, load_sources


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sources_file: Path = Path("sources.toml")
    data_dir: Path = Path("data")
    public_base_url: str = "http://localhost:8080"
    # Geheimes Pfadsegment, damit der Feed nicht offen im Netz steht.
    feed_secret: str = "change-me"
    feed_title: str = "OJS-Zeitschriften – Volltext"
    poll_interval_seconds: int = 6 * 3600
    max_articles_per_poll: int = 5
    max_attempts: int = 3
    feed_item_limit: int = 50
    http_timeout_seconds: float = 60.0
    user_agent: str = "medienpaed-reader/0.2 (+https://github.com/)"

    readwise_push: bool = False
    readwise_token: str | None = None
    readwise_location: str = "feed"

    docling_artifacts_path: Path | None = None
    docling_threads: int = 4

    host: str = "0.0.0.0"
    port: int = 8080

    @cached_property
    def sources(self) -> dict[str, Source]:
        return load_sources(self.sources_file)

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdf"

    @property
    def html_dir(self) -> Path:
        return self.data_dir / "html"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "articles.sqlite"

    @property
    def feed_path(self) -> str:
        return f"/feed/{self.feed_secret}.xml"

    def source_feed_path(self, source_key: str) -> str:
        return f"/feed/{self.feed_secret}/{source_key}.xml"

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.pdf_dir, self.html_dir):
            directory.mkdir(parents=True, exist_ok=True)
