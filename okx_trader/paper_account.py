"""Persistent per-profile virtual (paper) trading account.

Each profile (e.g. "15m", "4H", "1D") gets its own JSON state file with its
own starting balance, so results across profiles stay independently
comparable -- mirrors the approach used in the sister project (Hasanwavebot).
"""
import json
import os
from datetime import datetime, timezone

from . import strategy as strat

MAX_CLOSED_TRADES_KEPT = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _liquidation_price(entry_price: float, leverage: float, side: str) -> float:
    if side == "BUY":
        return entry_price * (1 - 1 / leverage)
    return entry_price * (1 + 1 / leverage)


def default_state(profile: str, leverage: float, margin_per_trade: float, starting_balance: float) -> dict:
    return {
        "profile": profile,
        "leverage": leverage,
        "margin_per_trade": margin_per_trade,
        "starting_balance": starting_balance,
        "balance": starting_balance,
        "open_positions": {},
        "closed_trades": [],
        "stats": {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
            "total_pnl": 0.0, "unrealized_pnl": 0.0,
        },
        "last_updated": _now_iso(),
    }


def load_state(path: str, profile: str, leverage: float, margin_per_trade: float, starting_balance: float) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_state(profile, leverage, margin_per_trade, starting_balance)


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _recompute_stats(state: dict) -> None:
    trades = state["closed_trades"]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    unrealized = sum(p["unrealized_pnl"] for p in state["open_positions"].values())
    state["stats"] = {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "total_pnl": round(state["balance"] - state["starting_balance"], 2),
        "unrealized_pnl": round(unrealized, 2),
    }


def update_symbol(state: dict, symbol: str, signal_row: dict, fee_rate: float = 0.0005) -> None:
    """Advance one symbol's position by one scan: check exits, mark-to-market, maybe enter."""
    leverage = state["leverage"]
    margin = state["margin_per_trade"]
    close = signal_row["close"]
    high = signal_row["high"]
    low = signal_row["low"]

    pos = state["open_positions"].get(symbol)
    if pos is not None:
        liq_price = _liquidation_price(pos["entry_price"], leverage, pos["side"])
        hit_sl = hit_tp = hit_liq = False
        if pos["side"] == "BUY":
            hit_liq = low <= liq_price
            hit_sl = low <= pos["sl"]
            hit_tp = high >= pos["tp"]
        else:
            hit_liq = high >= liq_price
            hit_sl = high >= pos["sl"]
            hit_tp = low <= pos["tp"]

        exit_price = reason = None
        if hit_liq:
            exit_price, reason = liq_price, "LIQUIDATION"
        elif hit_sl:
            exit_price, reason = pos["sl"], "SL"
        elif hit_tp:
            exit_price, reason = pos["tp"], "TP"

        if exit_price is not None:
            if pos["side"] == "BUY":
                gross = (exit_price - pos["entry_price"]) * pos["qty"]
            else:
                gross = (pos["entry_price"] - exit_price) * pos["qty"]
            fee = exit_price * pos["qty"] * fee_rate
            pnl = max(gross - fee, -pos["margin"])
            state["balance"] += pnl
            state["closed_trades"].append({
                "symbol": symbol, "side": pos["side"],
                "entry_time": pos["opened_at"], "entry_price": pos["entry_price"],
                "exit_time": _now_iso(), "exit_price": exit_price, "exit_reason": reason,
                "pnl": round(pnl, 4), "balance_after": round(state["balance"], 2),
            })
            state["closed_trades"] = state["closed_trades"][-MAX_CLOSED_TRADES_KEPT:]
            del state["open_positions"][symbol]
            pos = None
        else:
            if pos["side"] == "BUY":
                unrealized = (close - pos["entry_price"]) * pos["qty"]
            else:
                unrealized = (pos["entry_price"] - close) * pos["qty"]
            risk_amount = abs(pos["entry_price"] - pos["sl"]) * pos["qty"]
            pos["last_price"] = close
            pos["unrealized_pnl"] = round(unrealized, 2)
            pos["unrealized_r"] = round(unrealized / risk_amount, 2) if risk_amount else 0.0

    if pos is None and signal_row["signal"] in ("BUY", "SELL") and state["balance"] >= margin:
        side = signal_row["signal"]
        entry_price = close
        sl, tp = strat.compute_tp_sl(entry_price, signal_row["atr"], side)
        notional = margin * leverage
        qty = notional / entry_price
        entry_fee = notional * fee_rate
        state["balance"] -= entry_fee
        state["open_positions"][symbol] = {
            "symbol": symbol, "side": side, "entry_price": entry_price,
            "sl": sl, "tp": tp, "qty": qty, "margin": margin, "leverage": leverage,
            "opened_at": _now_iso(), "last_price": close,
            "unrealized_pnl": 0.0, "unrealized_r": 0.0,
        }

    _recompute_stats(state)
    state["last_updated"] = _now_iso()
