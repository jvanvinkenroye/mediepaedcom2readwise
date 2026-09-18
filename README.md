# medienpaed-reader

Volltext-Feed fuer die Zeitschrift [MedienPaedagogik](https://www.medienpaed.com/)
zum Lesen in Readwise Reader.

Der offizielle RSS-Feed verlinkt nur die Artikelseite, der Text steckt im PDF.
Dieser Dienst pollt den Feed, laedt das Haupt-PDF, wandelt es mit
[docling](https://github.com/docling-project/docling) in strukturiertes HTML um und
liefert einen eigenen RSS-Feed mit dem Volltext aus. Optional werden die Artikel
zusaetzlich direkt per Readwise-Reader-API angelegt.

Alle Beitraege der Zeitschrift stehen unter CC BY 4.0.

## Funktionsweise

```mermaid
flowchart TD
    subgraph quelle["medienpaed.com (OJS)"]
        RSS["RSS-Feed rss2<br/>nur Links auf Artikelseiten"]
        SEITE["Artikelseite<br/>citation_* Meta-Tags"]
        PDF["PDF-Galley<br/>(Haupttext, ggf. Anhang)"]
    end

    subgraph container["Docker-Container medienpaed-reader"]
        direction TB
        POLL["Poller<br/>alle 6 h, bei Backlog jede Minute"]
        DISC["discover<br/>neue Artikel-IDs als pending"]
        META["Metadaten lesen<br/>Titel, Autoren, DOI, Datum"]
        WAHL["Haupt-PDF waehlen<br/>groesste Datei per HEAD"]
        DL["PDF herunterladen"]
        DOC["docling<br/>CPU, kein OCR, Layout + Tabellen"]
        CLEAN["HTML bereinigen<br/>Silbentrennung, Seitenzahlen, Icon-Glyphen"]
        DB[("SQLite<br/>articles.sqlite")]
        FS[("Volume /data<br/>pdf/, html/")]
        WEB["Flask + waitress<br/>Port 8080 -> 8085"]
        PUSH["Readwise-Push<br/>POST /api/v3/save/ mit html"]
    end

    subgraph ziel["Readwise Reader"]
        FEEDABO["Feed-Abo<br/>/feed/&lt;secret&gt;.xml"]
        API["Dokument im Bereich Feed<br/>Tag medienpaed, URL = DOI"]
    end

    POLL --> DISC
    DISC -->|GET| RSS
    DISC --> DB
    DB -->|pending, max. 5 pro Lauf| META
    META -->|GET| SEITE
    META --> WAHL
    WAHL --> DL
    DL -->|GET| PDF
    DL --> FS
    DL --> DOC
    DOC --> CLEAN
    CLEAN --> FS
    CLEAN -->|status = done| DB
    DB --> WEB
    FS --> WEB
    WEB -->|"RSS 2.0 mit content:encoded<br/>+ /articles/&lt;id&gt;.html"| FEEDABO
    DB -->|done, noch nicht gepusht| PUSH
    FS --> PUSH
    PUSH -->|"201 neu / 200 Duplikat"| API
    PUSH -->|readwise_pushed_at| DB

    classDef quelle fill:#eef,stroke:#66a
    classDef ziel fill:#efe,stroke:#6a6
    classDef store fill:#ffe,stroke:#aa6
    class RSS,SEITE,PDF quelle
    class FEEDABO,API ziel
    class DB,FS store
```

Fehlerbehandlung: Jeder Artikel wird isoliert verarbeitet. Schlaegt ein Schritt fehl,
bleibt der Artikel pending und wird beim naechsten Lauf erneut versucht, nach
`MAX_ATTEMPTS` Versuchen wird er als failed markiert.

- Verarbeitete Artikel werden in SQLite (`DATA_DIR/articles.sqlite`) gefuehrt,
  PDFs und HTML liegen daneben.
- Bei mehreren PDF-Galleys (Haupttext + Anhang) wird die groesste Datei gewaehlt.
- Fehler werden pro Artikel isoliert, bis zu `MAX_ATTEMPTS` Versuche.
- Der Feed ist nur unter einem geheimen Pfadsegment erreichbar.

## Betrieb mit Docker

```bash
cp .env.example .env
# PUBLIC_BASE_URL und FEED_SECRET setzen (openssl rand -hex 16)
docker compose build
docker compose up -d
docker compose logs -f
```

Danach in Readwise Reader den Feed `https://<PUBLIC_BASE_URL>/feed/<FEED_SECRET>.xml`
abonnieren. Der Dienst gehoert hinter einen Reverse Proxy mit TLS.

Erststart: Der Dienst konvertiert die 20 aktuellen Feed-Eintraege
(`MAX_ARTICLES_PER_POLL` pro Durchlauf). Sollen Altartikel uebersprungen werden:

```bash
docker compose run --rm medienpaed-reader medienpaed-reader mark-known
```

Ressourcen: 2 CPU-Kerne und 4 GB RAM reichen. Ein Aufsatz mit 25 Seiten braucht
auf der CPU etwa eine Minute. Die docling-Modelle werden beim Image-Build geladen,
der Container braucht zur Laufzeit keinen Zugriff auf Hugging Face.

## Readwise-API-Push (optional)

```bash
READWISE_PUSH=true
READWISE_TOKEN=<Token von https://readwise.io/access_token>
READWISE_LOCATION=feed      # new | later | archive | feed
```

Artikel werden mit ihrem DOI als URL angelegt, Readwise erkennt Duplikate daran.
Manuell: `medienpaed-reader push-readwise --dry-run`.

## Lokale Entwicklung

```bash
uv sync
cp .env.example .env
uv run medienpaed-reader run-once --limit 1 -v
uv run medienpaed-reader serve --no-poll
curl localhost:8080/feed/<FEED_SECRET>.xml

uv run pytest
uv run ruff check src tests
uv run mypy src
```

## Kommandos

| Kommando | Zweck |
|---|---|
| `run-once [--limit N] [--skip-discover]` | Feed abfragen, neue Artikel konvertieren |
| `serve [--no-poll]` | Webserver, pollt im Hintergrund alle `POLL_INTERVAL_SECONDS` |
| `push-readwise [--dry-run]` | fertige Artikel an Readwise senden |
| `mark-known` | aktuelle Feed-Eintraege ueberspringen |

Alle Kommandos kennen `--verbose`, `--quiet` und `--data-dir`.

## Konfiguration

Siehe `.env.example`. Alle Werte kommen aus Umgebungsvariablen oder `.env`.
