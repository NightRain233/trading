from unittest.mock import MagicMock

import main


def _release_test_leader():
    handle = main._prewarm_leader_handle
    if handle is not None:
        handle.close()
    main._prewarm_leader_handle = None


def test_default_prewarm_schedule_includes_morning_refresh():
    assert main.PREWARM_TIMES == ((7, 30), (21, 0))


def test_next_prewarm_run_supports_half_past_seven():
    now = main.datetime(2026, 8, 19, 6, 45, tzinfo=main.PREWARM_TZ)

    assert main._next_prewarm_run(now).strftime("%H:%M") == "07:30"


def test_only_one_prewarm_leader_can_hold_lock(tmp_path):
    _release_test_leader()
    lock_path = tmp_path / "prewarm-leader.lock"
    try:
        assert main._try_become_prewarm_leader(str(lock_path)) is True
        first_handle = main._prewarm_leader_handle
        assert first_handle is not None

        main._prewarm_leader_handle = None
        assert main._try_become_prewarm_leader(str(lock_path)) is False
        assert main._prewarm_leader_handle is None
    finally:
        if "first_handle" in locals():
            first_handle.close()
        _release_test_leader()


def test_disabled_background_prewarm_starts_no_thread(monkeypatch):
    _release_test_leader()
    thread = MagicMock()
    monkeypatch.setattr(main, "BACKGROUND_PREWARM_ENABLED", False, raising=False)
    monkeypatch.setattr(main.threading, "Thread", thread)

    assert main._start_background_prewarm() is False
    thread.assert_not_called()


def test_only_leader_starts_background_thread(monkeypatch):
    _release_test_leader()
    fake_thread = MagicMock()
    thread_factory = MagicMock(return_value=fake_thread)
    monkeypatch.setattr(main, "BACKGROUND_PREWARM_ENABLED", True, raising=False)
    monkeypatch.setattr(
        main,
        "_try_become_prewarm_leader",
        lambda *_args, **_kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(main.threading, "Thread", thread_factory)

    assert main._start_background_prewarm() is True
    thread_factory.assert_called_once_with(
        target=main.refresh_watchlist_background,
        daemon=True,
        name="watchlist-prewarm",
    )
    fake_thread.start.assert_called_once_with()


def test_non_leader_starts_no_background_thread(monkeypatch):
    _release_test_leader()
    thread_factory = MagicMock()
    monkeypatch.setattr(main, "BACKGROUND_PREWARM_ENABLED", True, raising=False)
    monkeypatch.setattr(
        main,
        "_try_become_prewarm_leader",
        lambda *_args, **_kwargs: False,
        raising=False,
    )
    monkeypatch.setattr(main.threading, "Thread", thread_factory)

    assert main._start_background_prewarm() is False
    thread_factory.assert_not_called()
