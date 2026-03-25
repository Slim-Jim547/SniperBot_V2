import numpy as np
import pandas as pd
import pytest
from data.indicators import (
    ema, rsi, bollinger_bands, atr, adx, volume_ma, volume_ratio, compute_all
)


def make_series(values):
    return pd.Series(values, dtype=float)


def make_ohlcv(n=50, base=100.0, step=0.5):
    """Trending up OHLCV data for deterministic indicator testing."""
    closes = [base + i * step for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    opens = [base + (i - 1) * step if i > 0 else base for i in range(n)]
    volumes = [1000.0 + i * 10 for i in range(n)]
    return (
        make_series(opens),
        make_series(highs),
        make_series(lows),
        make_series(closes),
        make_series(volumes),
    )


class TestEMA:
    def test_constant_price_returns_same_value(self):
        prices = make_series([100.0] * 30)
        result = ema(prices, period=9)
        assert abs(result.iloc[-1] - 100.0) < 0.01

    def test_returns_series_same_length(self):
        prices = make_series([100.0 + i for i in range(20)])
        result = ema(prices, period=9)
        assert len(result) == 20

    def test_fast_ema_above_slow_in_uptrend(self):
        prices = make_series([100.0 + i for i in range(60)])
        fast = ema(prices, period=9)
        slow = ema(prices, period=21)
        assert fast.iloc[-1] > slow.iloc[-1]


class TestRSI:
    def test_returns_series_same_length(self):
        prices = make_series([100.0 + i for i in range(30)])
        result = rsi(prices, period=14)
        assert len(result) == 30

    def test_uptrend_gives_high_rsi(self):
        prices = make_series([100.0 + i for i in range(30)])
        result = rsi(prices, period=14)
        assert result.iloc[-1] > 60

    def test_downtrend_gives_low_rsi(self):
        prices = make_series([100.0 - i * 0.5 for i in range(30)])
        result = rsi(prices, period=14)
        assert result.iloc[-1] < 40

    def test_rsi_between_0_and_100(self):
        prices = make_series([100.0 + i for i in range(30)])
        result = rsi(prices, period=14).dropna()
        assert (result >= 0).all() and (result <= 100).all()


class TestBollingerBands:
    def test_constant_price_gives_zero_width(self):
        prices = make_series([100.0] * 30)
        middle, upper, lower, width_pct = bollinger_bands(prices, period=20, std_dev=2.0)
        assert abs(width_pct.iloc[-1]) < 1e-10

    def test_middle_is_rolling_mean(self):
        prices = make_series([float(i) for i in range(1, 31)])
        middle, _, _, _ = bollinger_bands(prices, period=20, std_dev=2.0)
        expected_middle = sum(range(11, 31)) / 20.0
        assert abs(middle.iloc[-1] - expected_middle) < 0.01

    def test_upper_above_lower(self):
        opens, highs, lows, closes, _ = make_ohlcv()
        middle, upper, lower, width_pct = bollinger_bands(closes, period=20, std_dev=2.0)
        assert (upper.dropna() > lower.dropna()).all()

    def test_returns_four_series(self):
        prices = make_series([100.0] * 30)
        result = bollinger_bands(prices)
        assert len(result) == 4


class TestATR:
    def test_constant_range_candles_give_atr_equal_to_range(self):
        n = 30
        highs = make_series([105.0] * n)
        lows = make_series([95.0] * n)
        closes = make_series([100.0] * n)
        result = atr(highs, lows, closes, period=14)
        # ATR of candles with identical 10-point high-low range = 10
        assert abs(result.iloc[-1] - 10.0) < 0.01

    def test_returns_series_same_length(self):
        _, highs, lows, closes, _ = make_ohlcv()
        result = atr(highs, lows, closes, period=14)
        assert len(result) == len(closes)

    def test_atr_positive(self):
        _, highs, lows, closes, _ = make_ohlcv()
        result = atr(highs, lows, closes, period=14).dropna()
        assert (result > 0).all()


class TestADX:
    def test_returns_three_series(self):
        _, highs, lows, closes, _ = make_ohlcv(n=60)
        adx_val, plus_di, minus_di = adx(highs, lows, closes, period=14)
        assert len(adx_val) == 60
        assert len(plus_di) == 60
        assert len(minus_di) == 60

    def test_strong_trend_gives_high_adx(self):
        n = 60
        closes = make_series([100.0 + i * 2 for i in range(n)])
        highs = make_series([c + 0.5 for c in closes])
        lows = make_series([c - 0.5 for c in closes])
        adx_val, _, _ = adx(highs, lows, closes, period=14)
        assert adx_val.iloc[-1] > 20

    def test_adx_non_negative(self):
        _, highs, lows, closes, _ = make_ohlcv(n=60)
        adx_val, plus_di, minus_di = adx(highs, lows, closes, period=14)
        assert (adx_val.dropna() >= 0).all()


class TestVolumeIndicators:
    def test_volume_ma_is_rolling_mean(self):
        volumes = make_series([1000.0] * 30)
        result = volume_ma(volumes, period=20)
        assert abs(result.iloc[-1] - 1000.0) < 0.01

    def test_volume_ratio_all_bullish(self):
        n = 30
        opens = make_series([100.0] * n)
        closes = make_series([101.0] * n)
        volumes = make_series([1000.0] * n)
        ratio = volume_ratio(opens, closes, volumes, period=20)
        assert ratio.iloc[-1] > 1.0


class TestComputeAll:
    def test_compute_all_returns_dict_with_required_keys(self):
        _, highs, lows, closes, volumes = make_ohlcv(n=60)
        opens = make_series([c - 0.3 for c in closes.tolist()])
        cfg_indicators = {
            "ema_fast": 9, "ema_slow": 21, "ema_trend": 50,
            "rsi_period": 14, "bb_period": 20, "bb_std": 2.0,
            "atr_period": 14, "adx_period": 14, "volume_ma_period": 20,
        }
        result = compute_all(opens, highs, lows, closes, volumes, cfg_indicators)
        required_keys = [
            "ema_fast", "ema_slow", "ema_trend",
            "rsi", "bb_middle", "bb_upper", "bb_lower", "bb_width_pct",
            "atr", "adx", "plus_di", "minus_di",
            "volume_ma", "volume_ratio",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_compute_all_returns_current_values_as_floats(self):
        _, highs, lows, closes, volumes = make_ohlcv(n=60)
        opens = make_series([c - 0.3 for c in closes.tolist()])
        cfg_indicators = {
            "ema_fast": 9, "ema_slow": 21, "ema_trend": 50,
            "rsi_period": 14, "bb_period": 20, "bb_std": 2.0,
            "atr_period": 14, "adx_period": 14, "volume_ma_period": 20,
        }
        result = compute_all(opens, highs, lows, closes, volumes, cfg_indicators)
        for key, val in result.items():
            assert isinstance(val, float), f"Key {key} is {type(val)}, expected float"
