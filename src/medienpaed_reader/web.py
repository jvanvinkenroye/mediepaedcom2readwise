"""Flask-App: Volltext-Feeds und Artikelseiten ausliefern."""

import hmac
from pathlib import Path

from flask import Flask, Response, abort, render_template

from medienpaed_reader.config import Settings
from medienpaed_reader.feed_output import build_feed
from medienpaed_reader.readwise_sync import source_line
from medienpaed_reader.store import ArticleRecord, Store


def _load_html(record: ArticleRecord) -> str:
    if not record.html_path:
        return ""
    path = Path(record.html_path)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def create_app(settings: Settings, store: Store) -> Flask:
    app = Flask(__name__)

    def _with_source_line(record: ArticleRecord) -> str:
        source = settings.sources.get(record.source)
        body = _load_html(record)
        return source_line(record, source) + body if source and body else body

    def _feed_response(xml: bytes) -> Response:
        return Response(xml, mimetype="application/rss+xml; charset=utf-8")

    def _secret_ok(secret: str) -> bool:
        return hmac.compare_digest(secret, settings.feed_secret)

    @app.get("/healthz")
    def healthz() -> Response:
        return Response("ok", mimetype="text/plain")

    @app.get("/feed/<secret>.xml")
    def feed(secret: str) -> Response:
        if not _secret_ok(secret):
            abort(404)
        return _feed_response(
            build_feed(
                store.done(settings.feed_item_limit),
                settings.sources,
                title=settings.feed_title,
                public_base_url=settings.public_base_url,
                feed_path=settings.feed_path,
                load_html=_with_source_line,
            )
        )

    @app.get("/feed/<secret>/<source_key>.xml")
    def source_feed(secret: str, source_key: str) -> Response:
        source = settings.sources.get(source_key)
        if not _secret_ok(secret) or source is None:
            abort(404)
        return _feed_response(
            build_feed(
                store.done(settings.feed_item_limit, source=source_key),
                {source_key: source},
                title=f"{source.name} – Volltext",
                public_base_url=settings.public_base_url,
                feed_path=settings.source_feed_path(source_key),
                load_html=_with_source_line,
                homepage=source.homepage,
            )
        )

    @app.get("/articles/<source_key>/<int:article_id>.html")
    def article(source_key: str, article_id: int) -> str:
        record = store.get(source_key, article_id)
        source = settings.sources.get(source_key)
        if record is None or record.status != "done" or source is None:
            abort(404)
        return render_template(
            "article.html", record=record, source=source, body=_load_html(record)
        )

    return app
