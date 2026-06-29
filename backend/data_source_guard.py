from __future__ import annotations

import fcntl
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool = True
    min_interval_seconds: float = 0.0
    duplicate_window_seconds: float = 300.0
    max_retries: int = 1
    backoff_seconds: float = 1.0
    failure_threshold: int = 3
    circuit_cooldown_seconds: float = 1800.0


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        key: str | None = None,
        category: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.key = key
        self.category = category or type(self).__name__
        self.retry_after = retry_after


class ProviderDisabledError(ProviderError):
    pass


class ProviderCircuitOpenError(ProviderError):
    pass


class ProviderRecentlySucceeded(ProviderError):
    pass


class ProviderBlockingError(ProviderError):
    """Signal from a transport that the remote side is actively blocking it."""


class ProviderRequestError(ProviderError):
    pass


class MarketDataUnavailableError(ProviderError):
    pass


def _default_state() -> dict:
    return {
        "lastAttemptAt": None,
        "lastSuccessAt": None,
        "nextAllowedAt": 0.0,
        "consecutiveFailures": 0,
        "circuitOpenUntil": 0.0,
        "lastErrorCategory": None,
        "lastErrorMessage": None,
        "recentSuccessByKey": {},
    }


class ProviderGuard(Generic[T]):
    def __init__(
        self,
        provider: str,
        config: ProviderConfig,
        *,
        state_dir: str | os.PathLike[str],
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        safe_provider = re.sub(r"[^a-zA-Z0-9_.-]+", "-", provider).strip("-")
        if not safe_provider:
            raise ValueError("provider name must contain a safe character")
        self.provider = safe_provider
        self.config = config
        self.state_dir = Path(state_dir)
        self.clock = clock
        self.sleep = sleep

    @property
    def _lock_path(self) -> Path:
        return self.state_dir / f"{self.provider}.lock"

    @property
    def _state_path(self) -> Path:
        return self.state_dir / f"{self.provider}.json"

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        state = _default_state()
        try:
            with self._state_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                state.update(payload)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            pass
        if not isinstance(state.get("recentSuccessByKey"), dict):
            state["recentSuccessByKey"] = {}
        return state

    def _save_state(self, state: dict) -> None:
        temporary_path = self._state_path.with_suffix(
            f".json.{os.getpid()}.tmp"
        )
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, self._state_path)

    def _with_locked_state(self, callback: Callable[[dict], T]) -> T:
        self._ensure_state_dir()
        with self._lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                return callback(self._load_state())
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _sanitize_error(exc: BaseException) -> str:
        return " ".join(str(exc).split())[:240]

    def _retry_after(self, deadline: float, now: float) -> int:
        return max(0, math.ceil(deadline - now))

    def _prune_recent_successes(self, state: dict, now: float) -> None:
        retention = max(
            self.config.duplicate_window_seconds * 4,
            24 * 60 * 60,
        )
        state["recentSuccessByKey"] = {
            key: float(timestamp)
            for key, timestamp in state["recentSuccessByKey"].items()
            if now - float(timestamp) <= retention
        }

    def call(self, key: str, operation: Callable[[], T]) -> T:
        if not self.config.enabled:
            raise ProviderDisabledError(
                f"{self.provider} provider is disabled",
                provider=self.provider,
                key=key,
                category="disabled",
            )

        def run(state: dict) -> T:
            now = self.clock()
            self._prune_recent_successes(state, now)

            circuit_open_until = float(state.get("circuitOpenUntil") or 0.0)
            if circuit_open_until > now:
                raise ProviderCircuitOpenError(
                    f"{self.provider} circuit is open",
                    provider=self.provider,
                    key=key,
                    category="circuit_open",
                    retry_after=self._retry_after(circuit_open_until, now),
                )

            previous_success = state["recentSuccessByKey"].get(key)
            if previous_success is not None:
                duplicate_deadline = (
                    float(previous_success)
                    + self.config.duplicate_window_seconds
                )
                if duplicate_deadline > now:
                    raise ProviderRecentlySucceeded(
                        f"{self.provider} request {key} recently succeeded",
                        provider=self.provider,
                        key=key,
                        category="duplicate",
                        retry_after=self._retry_after(duplicate_deadline, now),
                    )

            next_allowed_at = float(state.get("nextAllowedAt") or 0.0)
            if next_allowed_at > now:
                self.sleep(next_allowed_at - now)

            terminal_error: BaseException | None = None
            terminal_category = "request_error"
            for attempt in range(self.config.max_retries + 1):
                attempt_time = self.clock()
                state["lastAttemptAt"] = attempt_time
                state["nextAllowedAt"] = (
                    attempt_time + self.config.min_interval_seconds
                )
                self._save_state(state)
                try:
                    result = operation()
                except ProviderBlockingError as exc:
                    terminal_error = exc
                    terminal_category = "blocked"
                    break
                except Exception as exc:  # provider boundary
                    terminal_error = exc
                    terminal_category = type(exc).__name__
                    if attempt < self.config.max_retries:
                        self.sleep(
                            self.config.backoff_seconds * (2**attempt)
                        )
                        continue
                    break
                else:
                    success_time = self.clock()
                    state["lastSuccessAt"] = success_time
                    state["nextAllowedAt"] = max(
                        float(state.get("nextAllowedAt") or 0.0),
                        success_time + self.config.min_interval_seconds,
                    )
                    state["consecutiveFailures"] = 0
                    state["circuitOpenUntil"] = 0.0
                    state["lastErrorCategory"] = None
                    state["lastErrorMessage"] = None
                    state["recentSuccessByKey"][key] = success_time
                    self._prune_recent_successes(state, success_time)
                    self._save_state(state)
                    return result

            assert terminal_error is not None
            failure_time = self.clock()
            state["consecutiveFailures"] = (
                int(state.get("consecutiveFailures") or 0) + 1
            )
            state["lastErrorCategory"] = terminal_category
            state["lastErrorMessage"] = self._sanitize_error(terminal_error)

            opens_immediately = isinstance(
                terminal_error,
                ProviderBlockingError,
            )
            if (
                opens_immediately
                or state["consecutiveFailures"]
                >= self.config.failure_threshold
            ):
                state["circuitOpenUntil"] = (
                    failure_time + self.config.circuit_cooldown_seconds
                )

            self._save_state(state)
            circuit_deadline = float(state.get("circuitOpenUntil") or 0.0)
            retry_after = (
                self._retry_after(circuit_deadline, failure_time)
                if circuit_deadline > failure_time
                else None
            )
            raise ProviderRequestError(
                (
                    f"{self.provider} request failed "
                    f"({terminal_category}): "
                    f"{self._sanitize_error(terminal_error)}"
                ),
                provider=self.provider,
                key=key,
                category=terminal_category,
                retry_after=retry_after,
            ) from terminal_error

        return self._with_locked_state(run)

    def status(self) -> dict:
        def read(state: dict) -> dict:
            now = self.clock()
            circuit_open_until = float(
                state.get("circuitOpenUntil") or 0.0
            )
            return {
                "provider": self.provider,
                "enabled": self.config.enabled,
                "circuitState": (
                    "open" if circuit_open_until > now else "closed"
                ),
                "circuitOpenUntil": (
                    circuit_open_until if circuit_open_until else None
                ),
                "lastAttemptAt": state.get("lastAttemptAt"),
                "lastSuccessAt": state.get("lastSuccessAt"),
                "nextAllowedAt": state.get("nextAllowedAt") or None,
                "consecutiveFailures": int(
                    state.get("consecutiveFailures") or 0
                ),
                "lastErrorCategory": state.get("lastErrorCategory"),
                "lastErrorMessage": state.get("lastErrorMessage"),
            }

        return self._with_locked_state(read)
