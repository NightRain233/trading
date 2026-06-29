from __future__ import annotations

from dataclasses import dataclass

import pytest

from data_source_guard import (
    ProviderBlockingError,
    ProviderCircuitOpenError,
    ProviderConfig,
    ProviderDisabledError,
    ProviderGuard,
    ProviderRecentlySucceeded,
    ProviderRequestError,
)


@dataclass
class FakeTime:
    now: float = 1000.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def build_guard(tmp_path, fake_time, **overrides) -> ProviderGuard:
    config = ProviderConfig(
        enabled=overrides.pop("enabled", True),
        min_interval_seconds=overrides.pop("min_interval_seconds", 0.0),
        duplicate_window_seconds=overrides.pop("duplicate_window_seconds", 300.0),
        max_retries=overrides.pop("max_retries", 0),
        backoff_seconds=overrides.pop("backoff_seconds", 1.0),
        failure_threshold=overrides.pop("failure_threshold", 3),
        circuit_cooldown_seconds=overrides.pop("circuit_cooldown_seconds", 1800.0),
    )
    assert not overrides
    return ProviderGuard(
        "eastmoney",
        config,
        state_dir=tmp_path,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
    )


def test_disabled_provider_never_calls_operation(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(tmp_path, fake_time, enabled=False)
    called = False

    def operation():
        nonlocal called
        called = True

    with pytest.raises(ProviderDisabledError):
        guard.call("515880.SS", operation)

    assert not called
    assert guard.status()["enabled"] is False


def test_guard_spaces_different_request_keys(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(
        tmp_path,
        fake_time,
        min_interval_seconds=1.5,
    )
    call_times = []

    guard.call("A", lambda: call_times.append(fake_time.clock()) or "a")
    guard.call("B", lambda: call_times.append(fake_time.clock()) or "b")

    assert call_times == [1000.0, 1001.5]


def test_guard_suppresses_recently_successful_duplicate_key(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(tmp_path, fake_time, duplicate_window_seconds=300.0)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return "ok"

    assert guard.call("515880.SS", operation) == "ok"
    with pytest.raises(ProviderRecentlySucceeded) as exc_info:
        guard.call("515880.SS", operation)

    assert calls == 1
    assert exc_info.value.retry_after == 300


def test_blocking_signal_opens_circuit_immediately_without_retry(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(
        tmp_path,
        fake_time,
        max_retries=2,
        circuit_cooldown_seconds=60.0,
    )
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise ProviderBlockingError("empty reply from server")

    with pytest.raises(ProviderRequestError) as exc_info:
        guard.call("515880.SS", operation)

    assert calls == 1
    assert exc_info.value.category == "blocked"
    assert exc_info.value.retry_after == 60

    with pytest.raises(ProviderCircuitOpenError):
        guard.call("OTHER", lambda: "not reached")


def test_transient_failure_retries_with_backoff_then_resets_failures(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(
        tmp_path,
        fake_time,
        max_retries=1,
        backoff_seconds=2.0,
    )
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary timeout")
        return "ok"

    assert guard.call("515880.SS", operation) == "ok"
    assert calls == 2
    assert fake_time.clock() == 1002.0
    assert guard.status()["consecutiveFailures"] == 0


def test_repeated_terminal_failures_open_circuit_at_threshold(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(
        tmp_path,
        fake_time,
        failure_threshold=3,
        circuit_cooldown_seconds=90.0,
    )

    for key in ("A", "B", "C"):
        with pytest.raises(ProviderRequestError):
            guard.call(key, lambda: (_ for _ in ()).throw(TimeoutError(f"failed {key}")))

    status = guard.status()
    assert status["consecutiveFailures"] == 3
    assert status["circuitState"] == "open"
    assert status["circuitOpenUntil"] == 1090.0

    with pytest.raises(ProviderCircuitOpenError) as exc_info:
        guard.call("D", lambda: "not reached")
    assert exc_info.value.retry_after == 90


def test_status_sanitizes_and_truncates_last_error(tmp_path):
    fake_time = FakeTime()
    guard = build_guard(tmp_path, fake_time)
    unsafe_error = "secret-token\n" + ("x" * 500)

    with pytest.raises(ProviderRequestError):
        guard.call("A", lambda: (_ for _ in ()).throw(ValueError(unsafe_error)))

    status = guard.status()
    assert "\n" not in status["lastErrorMessage"]
    assert len(status["lastErrorMessage"]) <= 240
    assert status["lastErrorCategory"] == "ValueError"
