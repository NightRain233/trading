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
