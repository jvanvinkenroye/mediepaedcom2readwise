"""Flask-App: Volltext-Feed und Artikelseiten ausliefern."""

from pathlib import Path

from flask import Flask, Response, abort, render_template

from medienpaed_reader.config import Settings
from medienpaed_reader.feed_output import build_feed
from medienpaed_reader.store import ArticleRecord, Store


def _load_html(record: ArticleRecord) -> str:
    if not record.html_path:
        return ""
    path = Path(record.html_path)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def create_app(settings: Settings, store: Store) -> Flask:
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz() -> Response:
        return Response("ok", mimetype="text/plain")

    @app.get("/feed/<secret>.xml")
    def feed(secret: str) -> Response:
        if secret != settings.feed_secret:
            abort(404)
        xml = build_feed(
            store.done(settings.feed_item_limit),
            settings.public_base_url,
            settings.feed_path,
            _load_html,
        )
        return Response(xml, mimetype="application/rss+xml; charset=utf-8")

    @app.get("/articles/<int:article_id>.html")
    def article(article_id: int) -> str:
        record = store.get(article_id)
        if record is None or record.status != "done":
            abort(404)
        return render_template("article.html", record=record, body=_load_html(record))

    return app
