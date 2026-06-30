import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in choices else default


def _env_hours(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        hours = tuple(sorted({int(part.strip()) for part in raw.split(",")}))
    except (TypeError, ValueError):
        return default
    if not hours or any(hour < 0 or hour > 23 for hour in hours):
        return default
    return hours


DATA_DIR = "data"
CACHE_DURATION_SECONDS = 60 * 60
ALLOW_STALE_SECONDS = 60 * 60 * 24
DATA_RETENTION_DAYS = 1850
REFRESH_MIN_INTERVAL_SECONDS = 60

TICKFLOW_FETCH_ENABLED = _env_bool("TICKFLOW_FETCH_ENABLED", True)
TICKFLOW_BASE_URL = os.getenv(
    "TICKFLOW_BASE_URL",
    "https://free-api.tickflow.org",
).rstrip("/")
TICKFLOW_API_KEY = os.getenv("TICKFLOW_API_KEY", "").strip()
TICKFLOW_MIN_INTERVAL_SECONDS = _env_float(
    "TICKFLOW_MIN_INTERVAL_SECONDS",
    1.0,
)
TICKFLOW_CIRCUIT_COOLDOWN_SECONDS = _env_int(
    "TICKFLOW_CIRCUIT_COOLDOWN_SECONDS",
    900,
)
TICKFLOW_INCREMENTAL_OVERLAP_DAYS = _env_int(
    "TICKFLOW_INCREMENTAL_OVERLAP_DAYS",
    7,
    minimum=1,
)

YAHOO_FETCH_ENABLED = _env_bool("YAHOO_FETCH_ENABLED", True)
YAHOO_MIN_INTERVAL_SECONDS = _env_float(
    "YAHOO_MIN_INTERVAL_SECONDS",
    1.0,
)
YAHOO_CIRCUIT_COOLDOWN_SECONDS = _env_int(
    "YAHOO_CIRCUIT_COOLDOWN_SECONDS",
    900,
)

BACKGROUND_PREWARM_ENABLED = _env_bool("BACKGROUND_PREWARM_ENABLED", True)
PREWARM_HOURS = _env_hours("PREWARM_HOURS", (21,))

EMA_FAST_5 = 5
EMA_FAST_10 = 10
EMA_SHORT_PERIOD = 20
EMA_LONG_PERIOD = 50
ADX_PERIOD = 14
RSI_PERIODS = (7, 14, 21)

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLL_PERIOD = 20
BOLL_STD = 2

KDJ_PERIOD = 9
KDJ_SIGNAL_K = 3
KDJ_SIGNAL_D = 3

ATR_PERIOD = 14

ST_LENGTH = 7
ST_MULTIPLIER = 3.0

RESONANCE_GOLDEN_CROSS_LOOKBACK = 15
RESONANCE_PULLBACK_LOOKBACK = 3
RESONANCE_VOLUME_MA_WINDOW = 20
RESONANCE_VOLUME_SHRINK_RATIO = 0.8
RESONANCE_ESTABLISHED_TREND_LOOKBACK = 80
RESONANCE_ATR_STOP_MULTIPLIER = 1.5
RESONANCE_ATR_TARGET_MULTIPLIER = 3.0

RSI_THRESHOLDS = {
    "uptrend_strong": (75, 45),
    "downtrend_strong": (60, 25),
    "default": (70, 30),
}

CHART_DAYS = 100
MINI_CHART_DAYS = 30

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
