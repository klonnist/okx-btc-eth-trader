"""EMA-cross + RSI entry signal, confirmed by a higher-timeframe trend filter,
with ATR-based take-profit / stop-loss. This is a simple, explainable rules-based
strategy for analysis and backtesting purposes -- not a guarantee of future results.
"""
import pandas as pd

from . import indicators as ind

# Strategy parameters (kept in one place so backtest/live signal stay in sync)
TREND_EMA_FAST = 50
TREND_EMA_SLOW = 200
ENTRY_EMA_FAST = 12
ENTRY_EMA_SLOW = 26
RSI_PERIOD = 14
ATR_PERIOD = 14
RSI_LONG_RANGE = (35, 70)
RSI_SHORT_RANGE = (30, 65)
SL_ATR_MULT = 1.5
TP_ATR_MULT = 2.5


def build_trend_frame(df_trend: pd.DataFrame) -> pd.DataFrame:
    out = ind.add_indicators(df_trend, ema_fast=TREND_EMA_FAST, ema_slow=TREND_EMA_SLOW,
                              rsi_period=RSI_PERIOD, atr_period=ATR_PERIOD)
    out["trend"] = "neutral"
    out.loc[(out["ema_fast"] > out["ema_slow"]) & (out["close"] > out["ema_slow"]), "trend"] = "up"
    out.loc[(out["ema_fast"] < out["ema_slow"]) & (out["close"] < out["ema_slow"]), "trend"] = "down"
    return out


def build_entry_frame(df_entry: pd.DataFrame) -> pd.DataFrame:
    return ind.add_indicators(df_entry, ema_fast=ENTRY_EMA_FAST, ema_slow=ENTRY_EMA_SLOW,
                               rsi_period=RSI_PERIOD, atr_period=ATR_PERIOD)


def attach_trend(df_entry: pd.DataFrame, df_trend: pd.DataFrame) -> pd.DataFrame:
    """As-of merge: tag every entry-timeframe row with the last-closed higher-timeframe trend."""
    left = df_entry.sort_values("timestamp")
    right = df_trend[["timestamp", "trend"]].sort_values("timestamp")
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    merged["trend"] = merged["trend"].fillna("neutral")
    return merged


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Adds a `signal` column (BUY/SELL/NONE) on fresh EMA crosses aligned with trend + RSI filter."""
    out = df.copy()
    prev_fast = out["ema_fast"].shift(1)
    prev_slow = out["ema_slow"].shift(1)
    cross_up = (prev_fast <= prev_slow) & (out["ema_fast"] > out["ema_slow"])
    cross_down = (prev_fast >= prev_slow) & (out["ema_fast"] < out["ema_slow"])

    rsi_ok_long = out["rsi"].between(*RSI_LONG_RANGE)
    rsi_ok_short = out["rsi"].between(*RSI_SHORT_RANGE)

    out["signal"] = "NONE"
    out.loc[cross_up & (out["trend"] == "up") & rsi_ok_long, "signal"] = "BUY"
    out.loc[cross_down & (out["trend"] == "down") & rsi_ok_short, "signal"] = "SELL"
    return out


def compute_tp_sl(entry_price: float, atr_value: float, side: str) -> tuple[float, float]:
    """Returns (stop_loss, take_profit) prices for a BUY or SELL entry."""
    if side == "BUY":
        sl = entry_price - SL_ATR_MULT * atr_value
        tp = entry_price + TP_ATR_MULT * atr_value
    elif side == "SELL":
        sl = entry_price + SL_ATR_MULT * atr_value
        tp = entry_price - TP_ATR_MULT * atr_value
    else:
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    return sl, tp


def latest_signal(df_entry_raw: pd.DataFrame, df_trend_raw: pd.DataFrame) -> dict:
    """Convenience wrapper for live/current-bar analysis: returns a full report dict."""
    trend_df = build_trend_frame(df_trend_raw)
    entry_df = build_entry_frame(df_entry_raw)
    merged = attach_trend(entry_df, trend_df)
    signaled = generate_signals(merged)

    last = signaled.iloc[-1]
    report = {
        "timestamp": last["timestamp"],
        "close": float(last["close"]),
        "trend": last["trend"],
        "rsi": round(float(last["rsi"]), 2),
        "atr": float(last["atr"]),
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "signal": last["signal"],
    }
    if last["signal"] in ("BUY", "SELL"):
        sl, tp = compute_tp_sl(report["close"], report["atr"], last["signal"])
        report["stop_loss"] = sl
        report["take_profit"] = tp
    else:
        # Even with no fresh cross, report the current directional bias for context.
        bias = "BUY" if last["ema_fast"] > last["ema_slow"] else "SELL"
        sl, tp = compute_tp_sl(report["close"], report["atr"], bias)
        report["bias"] = bias
        report["bias_stop_loss"] = sl
        report["bias_take_profit"] = tp
    return report
