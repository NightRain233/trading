import importlib

import analysis_constants


def test_invalid_boolean_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "maybe")

    assert analysis_constants._env_bool("TEST_BOOL", True) is True
    assert analysis_constants._env_bool("TEST_BOOL", False) is False


def test_negative_numeric_values_fall_back_to_safe_default(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "-1")
    monkeypatch.setenv("TEST_INT", "-2")

    assert analysis_constants._env_float("TEST_FLOAT", 1.5) == 1.5
    assert analysis_constants._env_int("TEST_INT", 7) == 7


def test_proxy_mode_accepts_only_explicit_choices(monkeypatch):
    monkeypatch.setenv("TEST_PROXY_MODE", "automatic")

    assert analysis_constants._env_choice(
        "TEST_PROXY_MODE",
        "direct",
        {"direct", "environment"},
    ) == "direct"


def test_prewarm_hours_are_sorted_and_deduplicated(monkeypatch):
    monkeypatch.setenv("TEST_HOURS", "21,12,12")

    assert analysis_constants._env_hours(
        "TEST_HOURS",
        (12, 21),
    ) == (12, 21)


def test_invalid_prewarm_hours_fall_back(monkeypatch):
    monkeypatch.setenv("TEST_HOURS", "12,25")

    assert analysis_constants._env_hours(
        "TEST_HOURS",
        (12, 21),
    ) == (12, 21)


def test_prewarm_times_are_sorted_and_support_minutes(monkeypatch):
    monkeypatch.setenv("TEST_TIMES", "21:00,07:30,07:30")

    assert analysis_constants._env_times(
        "TEST_TIMES",
        ((21, 0),),
    ) == ((7, 30), (21, 0))


def test_invalid_prewarm_times_fall_back(monkeypatch):
    monkeypatch.setenv("TEST_TIMES", "07:30,25:00")

    assert analysis_constants._env_times(
        "TEST_TIMES",
        ((7, 30), (21, 0)),
    ) == ((7, 30), (21, 0))


def test_tickflow_defaults(monkeypatch):
    for key in (
        "TICKFLOW_FETCH_ENABLED",
        "TICKFLOW_BASE_URL",
        "TICKFLOW_API_KEY",
        "TICKFLOW_MIN_INTERVAL_SECONDS",
        "TICKFLOW_CIRCUIT_COOLDOWN_SECONDS",
        "TICKFLOW_INCREMENTAL_OVERLAP_DAYS",
        "PREWARM_HOURS",
        "PREWARM_TIMES",
    ):
        monkeypatch.delenv(key, raising=False)

    module = importlib.reload(analysis_constants)

    assert module.TICKFLOW_FETCH_ENABLED is True
    assert module.TICKFLOW_BASE_URL == "https://free-api.tickflow.org"
    assert module.TICKFLOW_API_KEY == ""
    assert module.TICKFLOW_MIN_INTERVAL_SECONDS == 1.0
    assert module.TICKFLOW_CIRCUIT_COOLDOWN_SECONDS == 900
    assert module.TICKFLOW_INCREMENTAL_OVERLAP_DAYS == 7
    assert module.PREWARM_TIMES == ((7, 30), (21, 0))
    assert module.PREWARM_HOURS == (7, 21)
