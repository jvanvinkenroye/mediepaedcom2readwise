from pathlib import Path

from medienpaed_reader import poller
from medienpaed_reader.config import Settings
from medienpaed_reader.store import Store


def _settings(tmp_path: Path) -> Settings:
    sources = tmp_path / "sources.toml"
    sources.write_text('[m]\nname="M"\nfeed_url="https://m/rss"\n', encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path, sources_file=sources, poll_interval_seconds=600
    )
    settings.ensure_dirs()
    return settings


def test_wait_or_wake_returns_early_on_wake_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        poller.request_wake(settings)

    assert poller.wait_or_wake(settings, 100, sleep=fake_sleep, check_every=5) is True
    assert slept == [5]
    assert not poller.wake_path(settings).exists()


def test_wait_or_wake_times_out_without_wake(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    clock = {"now": 0.0}
    poller.time.monotonic = lambda: clock["now"]  # type: ignore[assignment]

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    try:
        assert (
            poller.wait_or_wake(settings, 12, sleep=fake_sleep, check_every=5) is False
        )
        assert clock["now"] == 12
    finally:
        import time

        poller.time.monotonic = time.monotonic  # type: ignore[assignment]


def test_poller_keeps_converter_and_pause_depends_on_backlog(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.db_path)
    calls: list[object] = []

    def fake_run_once(
        settings_: Settings, store_: Store, converter: object = None
    ) -> object:
        calls.append(converter)
        return converter or "konverter"

    p = poller.Poller(settings, store, fake_run_once)
    p.run_one_cycle()
    p.run_one_cycle()
    assert calls == [None, "konverter"]
    assert p.pause_seconds() == 600
    store.upsert_pending("m", 1, "https://m/article/view/1", "x")
    assert p.pause_seconds() == poller.BACKLOG_PAUSE_SECONDS


def test_poller_survives_failing_cycle(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = Store(settings.db_path)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("kaputt")

    poller.Poller(settings, store, boom).run_one_cycle()  # darf nicht werfen
