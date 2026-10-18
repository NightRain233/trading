from concurrent.futures import Future

import pytest

import analysis_cache


class _NoBackgroundRefresh:
    """Stand-in for the stale-while-revalidate executor during tests.

    A real background refresh started by one test can outlive it and run while
    another test has patched the downloader, then write that test's fixture
    rows into the real ``backend/data`` cache (seen 2026-10-18: BTC-USD was
    overwritten with a one-row 2026-06-26 frame). Tests never need the real
    refresh to run, so submissions are recorded and completed immediately.
    """

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((getattr(fn, "__name__", repr(fn)), args))
        future = Future()
        future.set_result(None)
        return future


@pytest.fixture(autouse=True)
def _no_background_refresh(monkeypatch):
    monkeypatch.setattr(analysis_cache, "_refresh_executor", _NoBackgroundRefresh())
