"""
data/indicators.py

Single source of truth for all technical indicator calculations.
Every other module imports from here — never calculate indicators elsewhere.
All functions accept pandas Series, return pandas Series.
compute_all() returns the latest scalar values ready for strategy consumption.
"""

import numpy as np
import pandas as pd


def ema(closes: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return closes.ewm(span=period, adjust=False).mean()


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100)."""
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    # When avg_loss == 0 and avg_gain > 0, RSI = 100 (pure uptrend)
    # Use np.where on underlying arrays to avoid shape mismatch
    ag = avg_gain.values
    al = avg_loss.values
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(al == 0.0, np.inf, ag / al)
    rsi_arr = 100.0 - (100.0 / (1.0 + rs))
    return pd.Series(rsi_arr, index=closes.index)


def bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple:
    """
    Returns: (middle, upper, lower, width_pct)
    width_pct = (upper - lower) / middle  — used for squeeze detection.
    """
    middle = closes.rolling(period).mean()
    std = closes.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width_pct = (upper - lower) / middle.replace(0.0, np.nan)
    return middle, upper, lower, width_pct


def atr(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range using Wilder's smoothing (EWM)."""
    prev_close = closes.shift(1)
    true_range = pd.concat(
        [highs - lows, (highs - prev_close).abs(), (lows - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(com=period - 1, adjust=False).mean()


def adx(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    period: int = 14,
) -> tuple:
    """
    Average Directional Index using Wilder's smoothing.
    Returns: (adx, plus_di, minus_di)
    """
    up_move = highs.diff()
    down_move = -lows.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=highs.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=highs.index,
    )

    atr_val = atr(highs, lows, closes, period)
    smoothed_atr = atr_val.replace(0.0, np.nan)

    plus_di = 100.0 * plus_dm.ewm(com=period - 1, adjust=False).mean() / smoothed_atr
    minus_di = 100.0 * minus_dm.ewm(com=period - 1, adjust=False).mean() / smoothed_atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_val = dx.ewm(com=period - 1, adjust=False).mean()

    return adx_val, plus_di, minus_di


def volume_ma(volumes: pd.Series, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    return volumes.rolling(period).mean()


def volume_ratio(
    opens: pd.Series,
    closes: pd.Series,
    volumes: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Rolling buy/sell volume ratio.
    Buy volume = volume on candles where close >= open.
    Ratio > 1 means buyers are dominant.
    Uses same period as volume_ma for consistent lookback window.
    """
    buy_vol = volumes.where(closes >= opens, other=0.0)
    sell_vol = volumes.where(closes < opens, other=0.0)
    buy_sum = buy_vol.rolling(period).sum()
    sell_sum = sell_vol.rolling(period).sum()
    ratio = buy_sum / sell_sum.replace(0.0, np.nan)
    # When sell_sum is 0: pure buy pressure → ratio = buy_sum (large, > 1.0).
    # When both are 0 (no volume): ratio = 1.0 (neutral).
    return ratio.where(ratio.notna(), buy_sum.where(buy_sum > 0, 1.0))


def compute_all(
    opens: pd.Series,
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    volumes: pd.Series,
    cfg: dict,
) -> dict:
    """
    Compute all indicators and return current (last) scalar values.
    This is what the main loop calls on every candle close.

    Args:
        opens/highs/lows/closes/volumes: Full candle history as pandas Series
        cfg: The indicators section of config.yaml

    Returns:
        Dict of indicator name -> current float value
    """
    bb_mid, bb_up, bb_lo, bb_w = bollinger_bands(
        closes, period=cfg["bb_period"], std_dev=cfg["bb_std"]
    )
    adx_val, plus_di, minus_di = adx(
        highs, lows, closes, period=cfg["adx_period"]
    )

    def last(series: pd.Series) -> float:
        return float(series.iloc[-1])

    return {
        "ema_fast":      last(ema(closes, cfg["ema_fast"])),
        "ema_slow":      last(ema(closes, cfg["ema_slow"])),
        "ema_trend":     last(ema(closes, cfg["ema_trend"])),
        "rsi":           last(rsi(closes, cfg["rsi_period"])),
        "bb_middle":     last(bb_mid),
        "bb_upper":      last(bb_up),
        "bb_lower":      last(bb_lo),
        "bb_width_pct":  last(bb_w),
        "atr":           last(atr(highs, lows, closes, cfg["atr_period"])),
        "adx":           last(adx_val),
        "plus_di":       last(plus_di),
        "minus_di":      last(minus_di),
        "volume_ma":     last(volume_ma(volumes, cfg["volume_ma_period"])),
        # volume_ratio intentionally uses the same period as volume_ma —
        # both measure the same lookback window for consistency.
        "volume_ratio":  last(volume_ratio(opens, closes, volumes, cfg["volume_ma_period"])),
    }
