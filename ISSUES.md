# Offene Punkte

Stand: 2026-09-18, Ergebnis einer Code-Analyse (ruff --select ALL, radon, bandit,
pytest-cov). Testabdeckung 70 % (nach der Aufraeumrunde 88 %), Wartbarkeitsindex aller Module Stufe A.

Status: `[ ]` offen, `[x]` erledigt. Aufraeumrunde am 2026-09-18: Readwise-Abgleich
in `readwise_sync.py` ausgelagert, Funktionen aufgeteilt, Punkte unten abgehakt.

## Hoch

- [x] **Falsches PDF bei mehreren Galleys** (behoben 2026-09-18: alle Galleys laden, groesste Datei behalten) (`article_page.py`, `choose_main_pdf`)
  Die Auswahl der groessten Datei stuetzt sich auf `Content-Length` aus HEAD-Anfragen.
  medienpaed.com liefert den Header nicht, alle Groessen sind 0, der Fallback nimmt den
  ersten Eintrag. Bei Artikel 2665 ist das der Anhang (Galley 1623) statt des
  238-seitigen Haupttexts (1626). Auf brujah bereits so passiert und nach Readwise gepusht.
  Fix: Bei fehlender Groesse die ersten Kilobytes per GET streamen und Seitenzahl bzw.
  Dateigroesse vergleichen, oder das Galley-Label "PDF" von der Artikelseite auswerten.
  Danach `reset medienpaed 2665`, neu pushen, falsches Reader-Dokument entfernen.

- [x] **Eine SQLite-Verbindung ohne Sperre ueber mehrere Threads** (behoben 2026-09-18: RLock um jede Operation) (`store.py`, `Store.__init__`)
  Verbindung mit `check_same_thread=False`, gleichzeitig genutzt vom Poller-Thread und
  den vier waitress-Threads. Gleichzeitige Cursor fuehren zu `ProgrammingError` oder
  abgebrochenen Feed-Antworten.
  Fix: `threading.Lock` um jede Operation oder eine Verbindung pro Aufruf.

## Mittel

- [x] **Ein fehlgeschlagener Push stoppt alle folgenden** (behoben 2026-09-18: Fehler pro Artikel, Abbruch nur bei 429) (`pipeline.py`, `push_unpushed`)
  429 oder 5xx von Readwise bricht die Schleife ab, restliche Artikel warten bis zum
  naechsten Poll. Fix: Fehler pro Artikel fangen und loggen wie in `process_pending`.

- [x] **Feed-Secret-Vergleich mit `!=`** (`web.py`)
  Fuer LAN-Betrieb unkritisch; sauber ist `hmac.compare_digest`.

- [x] **`mark-known` missbraucht `mark_failed`** (`cli.py`)
  Status wird "failed" mit Fehlertext "uebersprungen". Eigener Status "skipped" waere
  ehrlicher und in `sources` getrennt zaehlbar.

- [x] **Testluecken** (2026-09-18: CLI-Tests mit CliRunner, Pipeline-Test mit web-Quelle, docling-Integrationstest unter Marker slow)
  `cli.py` 0 %, `pipeline.py` 48 %, `pdf_convert.convert` ungetestet.
  Fix: Integrationstest mit lokalem Editorial-PDF unter pytest-Marker `slow`,
  CLI-Tests mit `typer.testing.CliRunner`.

- [x] **`reset` stoesst den Poller nicht an** (2026-09-18: Marker-Datei `wake` im
  Datenverzeichnis, der Poller prueft sie alle 5 Sekunden; `reset` legt sie an)
  Ein zurueckgesetzter Artikel wartete sonst bis zum naechsten Intervall.

- [ ] **Neu konvertierte Artikel aktualisieren das Reader-Dokument nicht**
  Readwise erkennt die URL als Duplikat und laesst den Inhalt unveraendert.
  `reset --readwise` loest das manuell (loeschen, neu anlegen). Automatisch waere
  ein Vergleich von Inhalts-Hash und Push-Zeitpunkt noetig; Lesestand ginge verloren.

## Niedrig

- [x] `repush_doi_documents` (Komplexitaet 15) und `extract_article` (12) in Auswahl
  und Ausfuehrung aufteilen.
- [x] SHA-1 in `feed_source.py` mit `usedforsecurity=False` kennzeichnen (bandit B324).
- [x] Importe innerhalb von Funktionen sind Absicht (CLI ohne torch startbar); Kommentar
  am Modulanfang von `cli.py` und `pdf_convert.py` ergaenzen.
- [x] `Settings.sources` ist gecacht, Aenderungen an `sources.toml` brauchen einen
  Container-Neustart. Im README dokumentieren.
- [ ] docling-Konverter bleibt nach dem ersten Artikel dauerhaft im Speicher (ca. 2 GB).
  Seit 2026-09-18 wird er erst beim ersten OJS-Artikel geladen, nicht mehr beim Start.
  Fuer den 4-GB-Container in Ordnung, bei weiteren Quellen im Blick behalten.

## Bekannte Einschraenkungen (kein Fehler)

- bandit B608 in `store.py`: SQL-Stringbau nur mit festen Fragmenten und gebundenen
  Parametern, kein Risiko.
- Readwise-Dokumente zeigen die Domain der Artikel-URL als Quelle; `site_name` laesst
  sich per API nicht setzen.
- Quellentyp `web`: Paywall-Inhalte und per JavaScript nachgeladene Texte werden nicht
  erfasst; Seiten unter 300 Zeichen Lesetext gelten als Fehler.
- brujah.local ist nur im LAN erreichbar, deshalb ist der RSS-Ausgang ungenutzt und der
  Readwise-Push der aktive Weg.
