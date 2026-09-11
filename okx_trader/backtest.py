"""Leveraged long/short backtest engine.

Simplifications (this is a simulation, not a venue-accurate margin engine):
- One position open at a time, sized as `margin * leverage` notional.
- Entries fill at the signal bar's close; SL/TP are checked against the
  following bars' high/low. If a single bar's range touches both SL and TP,
  the stop-loss is assumed to hit first (conservative).
- Liquidation is approximated as entry_price * (1 -+ 1/leverage), capping the
  loss on any single trade at the posted margin.
- Fees are charged on both entry and exit notional at `fee_rate`.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import strategy as strat


@dataclass
class BacktestConfig:
    starting_balance: float = 10_000.0
    margin_per_trade: float = 500.0
    leverage: float = 5.0
    fee_rate: float = 0.0005  # 0.05% taker, applied on entry and exit notional


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    tp: float
    qty: float
    margin: float
    exit_time: pd.Timestamp = None
    exit_price: float = None
    exit_reason: str = None
    pnl: float = None
    balance_after: float = None


def _liquidation_price(entry_price: float, leverage: float, side: str) -> float:
    if side == "BUY":
        return entry_price * (1 - 1 / leverage)
    return entry_price * (1 + 1 / leverage)


def run_backtest(df: pd.DataFrame, config: BacktestConfig = BacktestConfig()) -> dict:
    """`df` must already carry `signal`, `atr`, `open/high/low/close`, `timestamp`."""
    balance = config.starting_balance
    position: Trade | None = None
    trades: list[Trade] = []
    equity_curve = []

    for _, row in df.iterrows():
        ts, high, low, close = row["timestamp"], row["high"], row["low"], row["close"]

        if position is not None:
            liq_price = _liquidation_price(position.entry_price, config.leverage, position.side)
            hit_sl = hit_tp = hit_liq = False
            if position.side == "BUY":
                hit_liq = low <= liq_price
                hit_sl = low <= position.sl
                hit_tp = high >= position.tp
            else:
                hit_liq = high >= liq_price
                hit_sl = high >= position.sl
                hit_tp = low <= position.tp

            exit_price = None
            reason = None
            if hit_liq:
                exit_price, reason = liq_price, "LIQUIDATION"
            elif hit_sl:
                exit_price, reason = position.sl, "SL"
            elif hit_tp:
                exit_price, reason = position.tp, "TP"

            if exit_price is not None:
                if position.side == "BUY":
                    gross_pnl = (exit_price - position.entry_price) * position.qty
                else:
                    gross_pnl = (position.entry_price - exit_price) * position.qty
                exit_fee = exit_price * position.qty * config.fee_rate
                pnl = max(gross_pnl - exit_fee, -position.margin)  # capped: can't lose more than margin

                balance += pnl
                position.exit_time = ts
                position.exit_price = exit_price
                position.exit_reason = reason
                position.pnl = pnl
                position.balance_after = balance
                trades.append(position)
                position = None

        if position is None and row["signal"] in ("BUY", "SELL") and balance >= config.margin_per_trade:
            side = row["signal"]
            entry_price = close
            sl, tp = strat.compute_tp_sl(entry_price, row["atr"], side)
            notional = config.margin_per_trade * config.leverage
            qty = notional / entry_price
            entry_fee = notional * config.fee_rate
            balance -= entry_fee
            position = Trade(
                side=side, entry_time=ts, entry_price=entry_price,
                sl=sl, tp=tp, qty=qty, margin=config.margin_per_trade,
            )

        unrealized = 0.0
        if position is not None:
            if position.side == "BUY":
                unrealized = (close - position.entry_price) * position.qty
            else:
                unrealized = (position.entry_price - close) * position.qty
        equity_curve.append({"timestamp": ts, "equity": balance + unrealized})

    equity_df = pd.DataFrame(equity_curve)
    summary = _summarize(trades, equity_df, config.starting_balance)
    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    return {"trades": trades_df, "equity_curve": equity_df, "summary": summary}


def _summarize(trades: list[Trade], equity_df: pd.DataFrame, starting_balance: float) -> dict:
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
            "final_balance": starting_balance, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "profit_factor": None,
        }

    pnls = np.array([t.pnl for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    final_balance = trades[-1].balance_after

    if not equity_df.empty:
        running_peak = equity_df["equity"].cummax()
        drawdown = (equity_df["equity"] - running_peak) / running_peak
        max_dd = drawdown.min() * 100
    else:
        max_dd = 0.0

    gross_profit = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0

    return {
        "total_trades": len(trades),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "final_balance": round(final_balance, 2),
        "total_return_pct": round((final_balance - starting_balance) / starting_balance * 100, 2),
        "max_drawdown_pct": round(float(max_dd), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
    }


def prepare_signal_frame(df_entry_raw: pd.DataFrame, df_trend_raw: pd.DataFrame) -> pd.DataFrame:
    trend_df = strat.build_trend_frame(df_trend_raw)
    entry_df = strat.build_entry_frame(df_entry_raw)
    merged = strat.attach_trend(entry_df, trend_df)
    return strat.generate_signals(merged)
