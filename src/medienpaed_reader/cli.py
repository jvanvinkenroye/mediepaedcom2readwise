"""Kommandozeile: run-once, serve, push-readwise, sources, reset.

Die Pipeline-Module werden erst in den Kommandos importiert: docling zieht torch mit,
das dauert Sekunden und ist fuer --help, sources oder reset nicht noetig.
"""

import logging
from pathlib import Path
from typing import Annotated

import typer

from medienpaed_reader.config import Settings
from medienpaed_reader.poller import request_wake
from medienpaed_reader.store import Store

app = typer.Typer(help="Volltext-Feeds fuer OJS-Zeitschriften und Readwise Reader.")

VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Debug-Ausgabe")]
QuietOpt = Annotated[bool, typer.Option("--quiet", "-q", help="Nur Fehler ausgeben")]
DataDirOpt = Annotated[
    Path | None, typer.Option("--data-dir", help="Ueberschreibt DATA_DIR")
]


def _setup(verbose: bool, quiet: bool, data_dir: Path | None) -> tuple[Settings, Store]:
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("docling").setLevel(max(level, logging.WARNING))
    settings = Settings()
    if data_dir is not None:
        settings.data_dir = data_dir
    settings.ensure_dirs()
    return settings, Store(settings.db_path)


@app.command("run-once")
def run_once(
    limit: Annotated[
        int | None, typer.Option(help="Max. Artikel in diesem Lauf")
    ] = None,
    skip_discover: Annotated[
        bool, typer.Option(help="Feed nicht abfragen, nur pending abarbeiten")
    ] = False,
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Feed einmal abfragen und neue Artikel konvertieren."""
    from medienpaed_reader import pipeline

    settings, store = _setup(verbose, quiet, data_dir)
    pipeline.run_once(settings, store, limit=limit, skip_discover=skip_discover)


@app.command("mark-known")
def mark_known(
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Aktuelle Feed-Eintraege als bekannt markieren, ohne sie zu konvertieren.

    Nuetzlich beim Erststart, wenn keine Altartikel nachgeliefert werden sollen.
    """
    from medienpaed_reader import pipeline

    settings, store = _setup(verbose, quiet, data_dir)
    with pipeline.make_http_client(settings) as client:
        pipeline.discover(settings, store, client)
    for record in store.pending(limit=1000):
        store.mark_skipped(record.source, record.article_id, "mark-known")
    typer.echo("Feed-Eintraege als bekannt markiert.")


@app.command()
def sources(
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Konfigurierte Quellen und Artikelzaehler anzeigen."""
    settings, store = _setup(verbose, quiet, data_dir)
    counts = store.counts()
    for source in settings.sources.values():
        typer.echo(f"{source.key}: {source.name} <{source.feed_url}>")
        for src, status, n in counts:
            if src == source.key:
                typer.echo(f"    {status}: {n}")


@app.command()
def reset(
    source: Annotated[str, typer.Argument(help="Quellen-Schluessel, z. B. medienpaed")],
    article_id: Annotated[int, typer.Argument(help="Artikel-ID aus der URL")],
    readwise: Annotated[
        bool, typer.Option("--readwise", help="Auch das Reader-Dokument loeschen")
    ] = False,
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Artikel erneut zur Verarbeitung freigeben, optional samt Neu-Push."""
    from medienpaed_reader import readwise_sync

    settings, store = _setup(verbose, quiet, data_dir)
    record = store.get(source, article_id)
    if record is None:
        typer.echo(f"{source}/{article_id} nicht gefunden.", err=True)
        raise typer.Exit(code=1)
    if readwise:
        deleted = readwise_sync.forget_in_readwise(settings, store, record)
        typer.echo(f"{deleted} Reader-Dokument(e) geloescht.")
    store.reset(source, article_id)
    request_wake(settings)
    typer.echo(f"{source}/{article_id} steht wieder auf pending, Poller geweckt.")


@app.command("push-readwise")
def push_readwise(
    dry_run: Annotated[bool, typer.Option(help="Nur anzeigen, nichts senden")] = False,
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Alle fertigen, noch nicht gepushten Artikel an Readwise Reader senden."""
    from medienpaed_reader import readwise_sync

    settings, store = _setup(verbose, quiet, data_dir)
    count = readwise_sync.push_unpushed(settings, store, dry_run=dry_run)
    typer.echo(f"{count} Artikel gepusht.")


@app.command("readwise-repush")
def readwise_repush(
    dry_run: Annotated[
        bool, typer.Option(help="Nur anzeigen, nichts loeschen")
    ] = False,
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Eigene Reader-Dokumente mit doi.org-URL loeschen und neu anlegen."""
    from medienpaed_reader import readwise_sync

    settings, store = _setup(verbose, quiet, data_dir)
    deleted, pushed = readwise_sync.repush_doi_documents(
        settings, store, dry_run=dry_run
    )
    typer.echo(f"{deleted} geloescht, {pushed} neu gepusht.")


@app.command()
def serve(
    no_poll: Annotated[
        bool, typer.Option(help="Nur Webserver, kein Hintergrund-Polling")
    ] = False,
    verbose: VerboseOpt = False,
    quiet: QuietOpt = False,
    data_dir: DataDirOpt = None,
) -> None:
    """Webserver starten; pollt im Hintergrund alle POLL_INTERVAL_SECONDS."""
    from waitress import serve as waitress_serve

    from medienpaed_reader import pipeline
    from medienpaed_reader.web import create_app

    settings, store = _setup(verbose, quiet, data_dir)
    log = logging.getLogger("medienpaed_reader.serve")

    if not no_poll:
        from medienpaed_reader.poller import Poller

        Poller(settings, store, pipeline.run_once).start_thread()

    log.info("Feed erreichbar unter %s%s", settings.public_base_url, settings.feed_path)
    waitress_serve(
        create_app(settings, store), host=settings.host, port=settings.port, threads=4
    )


if __name__ == "__main__":
    app()
