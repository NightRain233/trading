from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from collections.abc import Callable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from .models import AssetConfig, DataDiagnostic, StrategyConfig
from .schedules import xshg_sessions


SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
A_SHARE_CLOSE_CUTOFF = time(15, 10)
REQUIRED_OHLC = ("Open", "High", "Low", "Close")


@dataclass(frozen=True)
class PortfolioMarketData:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    sessions: pd.DatetimeIndex
    market_data_date: date | None
    diagnostics: tuple[DataDiagnostic, ...]

    @property
    def blocked(self) -> bool:
        return any(
            diagnostic.code.startswith("BLOCKED_")
            for diagnostic in self.diagnostics
        )


@dataclass(frozen=True)
class RefreshResult:
    symbols: tuple[str, ...]
    completed: bool


def _aware_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now


def _normalize_frame(frame: pd.DataFrame, market: str) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    index = pd.DatetimeIndex(normalized.index)
    if index.tz is not None:
        if market == "CRYPTO_UTC":
            index = index.tz_convert(UTC)
        index = index.tz_localize(None)
    normalized.index = index.normalize()
    normalized = normalized[~normalized.index.duplicated(keep="last")].sort_index()
    available = [column for column in REQUIRED_OHLC if column in normalized]
    if available:
        normalized = normalized.dropna(subset=available)
    return normalized


def filter_completed_rows(
    asset: AssetConfig,
    frame: pd.DataFrame,
    now: datetime,
) -> pd.DataFrame:
    normalized = _normalize_frame(frame, asset.market)
    current = _aware_now(now)
    if asset.market == "CRYPTO_UTC":
        latest_allowed = current.astimezone(UTC).date() - timedelta(days=1)
    else:
        shanghai_now = current.astimezone(SHANGHAI)
        latest_allowed = shanghai_now.date()
        if shanghai_now.time() < A_SHARE_CLOSE_CUTOFF:
            latest_allowed -= timedelta(days=1)
    return normalized[normalized.index.date <= latest_allowed].copy()


def _latest_expected_xshg_session(now: datetime) -> pd.Timestamp | None:
    shanghai_now = _aware_now(now).astimezone(SHANGHAI)
    end = shanghai_now.date()
    if shanghai_now.time() < A_SHARE_CLOSE_CUTOFF:
        end -= timedelta(days=1)
    sessions = xshg_sessions(end - timedelta(days=30), end)
    return sessions[-1] if not sessions.empty else None


def _minimum_history(config: StrategyConfig) -> int:
    if config.strategy_id == "theme_alpha":
        return max(
            int(config.params["defense_ma_window"]),
            int(config.params["momentum_window"]) + 1,
            int(config.params["volatility_window"]),
            int(config.params["risk_parity_window"]) + 1,
        )
    return max(
        int(config.params["supertrend_atr_window"]) + 1,
        int(config.params["risk_parity_window"]) + 1,
    )


def _empty_market_data(
    diagnostics: list[DataDiagnostic],
) -> PortfolioMarketData:
    return PortfolioMarketData(
        open=pd.DataFrame(),
        high=pd.DataFrame(),
        low=pd.DataFrame(),
        close=pd.DataFrame(),
        sessions=pd.DatetimeIndex([]),
        market_data_date=None,
        diagnostics=tuple(diagnostics),
    )


def build_portfolio_market_data(
    config: StrategyConfig,
    frames: Mapping[str, pd.DataFrame],
    now: datetime,
) -> PortfolioMarketData:
    diagnostics: list[DataDiagnostic] = []
    completed: dict[str, pd.DataFrame] = {}
    for asset in config.assets:
        source = frames.get(asset.symbol)
        if source is None or source.empty:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_MISSING_DATA",
                    "Required market data is missing",
                    asset.symbol,
                )
            )
            continue
        missing_columns = [
            column for column in REQUIRED_OHLC if column not in source.columns
        ]
        if missing_columns:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_MISSING_DATA",
                    "Required OHLC columns are missing",
                    asset.symbol,
                    {"columns": tuple(missing_columns)},
                )
            )
            continue
        clean = filter_completed_rows(asset, source, now)
        if clean.empty:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_INCOMPLETE_CLOSE",
                    "No completed daily close is available",
                    asset.symbol,
                )
            )
            continue
        completed[asset.symbol] = clean

    etf_symbols = [
        asset.symbol
        for asset in config.assets
        if asset.market == "XSHG" and asset.symbol in completed
    ]
    if not etf_symbols:
        return _empty_market_data(diagnostics)

    expected_latest = _latest_expected_xshg_session(now)
    latest_by_symbol = {
        symbol: completed[symbol].index.max() for symbol in etf_symbols
    }
    candidate = max(latest_by_symbol.values())
    if expected_latest is not None and candidate < expected_latest:
        diagnostics.append(
            DataDiagnostic(
                "BLOCKED_STALE_DATA",
                "Latest ETF close is older than the latest completed XSHG session",
                details={
                    "latest": candidate.date().isoformat(),
                    "expected": expected_latest.date().isoformat(),
                },
            )
        )

    for symbol in etf_symbols:
        if candidate not in completed[symbol].index:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_SESSION_MISMATCH",
                    "Asset is missing the latest portfolio session",
                    symbol,
                    {"session": candidate.date().isoformat()},
                )
            )

    recent_expected = xshg_sessions(
        candidate.date() - timedelta(days=45),
        candidate.date(),
    )[-20:]
    for symbol in etf_symbols:
        available = completed[symbol].index
        missing = recent_expected.difference(available)
        for session in missing:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_MISSING_SESSION",
                    "Asset has an unexplained recent session gap",
                    symbol,
                    {"session": session.date().isoformat()},
                )
            )

    common_sessions = completed[etf_symbols[0]].index
    for symbol in etf_symbols[1:]:
        common_sessions = common_sessions.intersection(completed[symbol].index)
    common_sessions = common_sessions[common_sessions <= candidate].sort_values()
    if common_sessions.empty:
        return _empty_market_data(diagnostics)

    for asset in config.assets:
        frame = completed.get(asset.symbol)
        if frame is None:
            continue
        frame_dates = frame.index
        check_sessions = common_sessions[
            (common_sessions >= frame_dates.min()) & (common_sessions <= frame_dates.max())
        ]
        missing_common = check_sessions.difference(frame_dates)
        if not missing_common.empty:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_SESSION_MISMATCH",
                    "Asset cannot align to the ETF decision calendar",
                    asset.symbol,
                    {"session": missing_common[-1].date().isoformat()},
                )
            )

    minimum_history = _minimum_history(config)
    for symbol, frame in completed.items():
        available_rows = int((frame.index <= candidate).sum())
        if available_rows < minimum_history:
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_INSUFFICIENT_HISTORY",
                    "Not enough completed history for strategy indicators",
                    symbol,
                    {
                        "required": minimum_history,
                        "available": available_rows,
                    },
                )
            )

    def field_frame(field: str) -> pd.DataFrame:
        columns = {}
        for symbol in config.symbols:
            frame = completed.get(symbol)
            if frame is None:
                columns[symbol] = pd.Series(index=common_sessions, dtype=float)
            else:
                columns[symbol] = frame[field].reindex(common_sessions)
        return pd.DataFrame(columns, index=common_sessions)

    open_frame = field_frame("Open")
    high_frame = field_frame("High")
    low_frame = field_frame("Low")
    close_frame = field_frame("Close")
    for symbol in config.symbols:
        col = close_frame.get(symbol)
        if col is None or symbol not in completed:
            continue
        recent = col.tail(5)
        if recent.isna().any():
            diagnostics.append(
                DataDiagnostic(
                    "BLOCKED_SESSION_MISMATCH",
                    "Recent aligned strategy history contains missing closes",
                    symbol,
                )
            )

    return PortfolioMarketData(
        open=open_frame,
        high=high_frame,
        low=low_frame,
        close=close_frame,
        sessions=common_sessions,
        market_data_date=common_sessions[-1].date(),
        diagnostics=tuple(diagnostics),
    )


def load_strategy_market_data(
    config: StrategyConfig,
    data_dir: Path | str,
    now: datetime,
) -> PortfolioMarketData:
    root = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for symbol in config.symbols:
        path = root / f"{symbol.upper()}.parquet"
        if path.exists():
            frames[symbol] = pd.read_parquet(path)
    return build_portfolio_market_data(config, frames, now)


def refresh_strategy_universe(
    config: StrategyConfig,
    timeout_seconds: float,
    *,
    refresh_fn: Callable | None = None,
) -> RefreshResult:
    if refresh_fn is None:
        from analysis_cache import refresh_symbols_sync_with_timeout

        refresh_fn = refresh_symbols_sync_with_timeout
    symbols = list(config.symbols)
    completed = bool(
        refresh_fn(
            symbols,
            timeout_seconds,
            reason="portfolio_strategy",
            min_interval_seconds=0,
        )
    )
    return RefreshResult(config.symbols, completed)
