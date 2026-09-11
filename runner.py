#!/usr/bin/env python
"""One scan of a live paper-trading profile against OKX market data.

Meant to be invoked periodically (e.g. by a GitHub Actions cron) with
    python runner.py --profile 15m --timeframe 15m --leverage 10

State persists to docs/data/<profile>/state.json so the static dashboard in
docs/ can read it directly (both live under the same GitHub Pages root).
No real orders are ever placed -- this only reads public OKX market data and
updates a local JSON ledger.
"""
import argparse
import os

from okx_trader import okx_client, paper_account as pa
from okx_trader.backtest import prepare_signal_frame

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
DATA_DIR = os.path.join(os.path.dirname(__file__), "docs", "data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Klasor/etiket adi, orn. 15m")
    parser.add_argument("--timeframe", required=True, help="OKX bar kodu, orn. 15m/4H/1D")
    parser.add_argument("--trend-timeframe", default="1D", dest="trend_timeframe")
    parser.add_argument("--leverage", type=float, required=True)
    parser.add_argument("--margin", type=float, default=500.0)
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    args = parser.parse_args()

    state_path = os.path.join(DATA_DIR, args.profile, "state.json")
    state = pa.load_state(state_path, args.profile, args.leverage, args.margin, args.balance)

    for symbol in args.symbols:
        trend_raw = okx_client.fetch_recent_candles(symbol, args.trend_timeframe, limit=300)
        entry_raw = trend_raw if args.timeframe == args.trend_timeframe else okx_client.fetch_recent_candles(symbol, args.timeframe, limit=300)
        signal_df = prepare_signal_frame(entry_raw, trend_raw)
        last = signal_df.iloc[-1]
        pa.update_symbol(state, symbol, last.to_dict())
        print(f"[{args.profile}] {symbol}: close={last['close']:.4f} signal={last['signal']} trend={last['trend']}")

    pa.save_state(state_path, state)
    print(f"[{args.profile}] bakiye={state['balance']:.2f} acik={len(state['open_positions'])} "
          f"islem={state['stats']['total_trades']} kazanma={state['stats']['win_rate_pct']}%")


if __name__ == "__main__":
    main()
