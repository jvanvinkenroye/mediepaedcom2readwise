"""Hintergrund-Poller: periodische Durchlaeufe, Backlog-Modus und Weckruf.

Der Poller schlaeft in kurzen Schritten und prueft dabei eine Marker-Datei im
Datenverzeichnis. Kommandos wie `reset` legen sie an, damit der naechste Durchlauf
sofort startet statt erst nach dem vollen Intervall.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from medienpaed_reader.config import Settings
from medienpaed_reader.pdf_convert import PdfConverter
from medienpaed_reader.store import Store

log = logging.getLogger(__name__)

WAKE_FILE = "wake"
BACKLOG_PAUSE_SECONDS = 60
WAKE_CHECK_SECONDS = 5


def wake_path(settings: Settings) -> Path:
    return settings.data_dir / WAKE_FILE


def request_wake(settings: Settings) -> None:
    """Naechsten Poll-Durchlauf sofort anfordern."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    wake_path(settings).touch()


def consume_wake(settings: Settings) -> bool:
    path = wake_path(settings)
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


def wait_or_wake(
    settings: Settings,
    seconds: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    check_every: float = WAKE_CHECK_SECONDS,
) -> bool:
    """Bis zu `seconds` warten; True, wenn ein Weckruf die Wartezeit beendet hat."""
    deadline = time.monotonic() + seconds
    while True:
        if consume_wake(settings):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        sleep(min(check_every, remaining))


class Poller:
    """Fuehrt run_once in einer Endlosschleife aus und haelt den Konverter vor."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        run_once: Callable[..., PdfConverter | None],
    ) -> None:
        self._settings = settings
        self._store = store
        self._run_once = run_once
        self._converter: PdfConverter | None = None

    def run_one_cycle(self) -> None:
        try:
            # run_once erzeugt den Konverter nur bei OJS-Artikeln und gibt ihn zurueck;
            # wir behalten ihn, damit die Modelle nicht bei jedem Lauf neu laden.
            self._converter = self._run_once(
                self._settings, self._store, converter=self._converter
            )
        except Exception:  # noqa: BLE001 - Poller darf nicht sterben
            log.exception("Poll-Durchlauf fehlgeschlagen")

    def pause_seconds(self) -> float:
        backlog = bool(self._store.pending(limit=1))
        return (
            BACKLOG_PAUSE_SECONDS if backlog else self._settings.poll_interval_seconds
        )

    def run_forever(self) -> None:
        consume_wake(self._settings)
        while True:
            self.run_one_cycle()
            if wait_or_wake(self._settings, self.pause_seconds()):
                log.info("Weckruf erhalten, starte Durchlauf")

    def start_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="poller", daemon=True)
        thread.start()
        return thread
