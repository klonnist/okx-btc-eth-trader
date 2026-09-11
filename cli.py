#!/usr/bin/env python
"""CLI for the OKX BTC/ETH analysis + backtest tool.

    python cli.py analyze
    python cli.py backtest --symbol BTC-USDT-SWAP --entry-timeframe 4H --start 2024-01-01 --end 2024-12-31

This is an educational technical-analysis / simulation tool. Nothing here places
real orders -- it only reads public OKX market data and simulates outcomes.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from okx_trader import okx_client, strategy as strat
from okx_trader.backtest import BacktestConfig, prepare_signal_frame, run_backtest

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
ENTRY_TIMEFRAMES = ["15m", "4H", "1D"]
BACKTESTS_DIR = os.path.join(os.path.dirname(__file__), "docs", "data", "backtests")

BAR_TIMEDELTA = {
    "1m": timedelta(minutes=1), "3m": timedelta(minutes=3), "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15), "30m": timedelta(minutes=30),
    "1H": timedelta(hours=1), "2H": timedelta(hours=2), "4H": timedelta(hours=4),
    "6H": timedelta(hours=6), "12H": timedelta(hours=12),
    "1D": timedelta(days=1), "1W": timedelta(days=7),
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _fmt(x, nd=2):
    return f"{x:,.{nd}f}" if isinstance(x, (int, float)) else x


def cmd_analyze(args):
    print("=" * 72)
    print("CANLI TEKNIK ANALIZ -- OKX verisi (egitim/analiz amaclidir, yatirim tavsiyesi degildir)")
    print("=" * 72)
    for symbol in args.symbols:
        trend_raw = okx_client.fetch_recent_candles(symbol, args.trend_timeframe, limit=300)
        for tf in args.entry_timeframes:
            entry_raw = trend_raw if tf == args.trend_timeframe else okx_client.fetch_recent_candles(symbol, tf, limit=300)
            report = strat.latest_signal(entry_raw, trend_raw)

            print(f"\n[{symbol}] entry={tf} trend={args.trend_timeframe} @ {report['timestamp']}")
            print(f"  Fiyat: {_fmt(report['close'])}  RSI: {report['rsi']}  Trend(ust zaman dilimi): {report['trend']}")
            if report["signal"] in ("BUY", "SELL"):
                notional = args.margin * args.leverage
                qty = notional / report["close"]
                print(f"  >>> SINYAL: {report['signal']}  (taze EMA kesisimi, trend ile uyumlu)")
                print(f"      Giris : {_fmt(report['close'])}")
                print(f"      SL    : {_fmt(report['stop_loss'])}")
                print(f"      TP    : {_fmt(report['take_profit'])}")
                print(f"      Pozisyon: {args.leverage}x kaldirac, {_fmt(args.margin)} USDT marjin -> {_fmt(notional)} USDT notional (~{qty:.6f} adet)")
            else:
                print(f"  Sinyal yok. Mevcut yon egilimi: {report['bias']} "
                      f"(referans SL {_fmt(report['bias_stop_loss'])} / TP {_fmt(report['bias_take_profit'])})")
    print("\nNot: Bu cikti otomatik uretilmis teknik analizdir, kesin alim/satim komutu degildir. Risk yonetimi size aittir.")


def cmd_backtest(args):
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") if args.end else pd.Timestamp.now(tz="UTC")

    entry_warmup = BAR_TIMEDELTA[args.entry_timeframe] * 300
    trend_warmup = timedelta(days=400)

    print(f"Veri cekiliyor: {args.symbol} entry={args.entry_timeframe} trend={args.trend_timeframe} "
          f"[{start.date()} -> {end.date()}] ...")
    entry_raw = okx_client.fetch_history_candles(args.symbol, args.entry_timeframe, start - entry_warmup, end)
    trend_raw = okx_client.fetch_history_candles(args.symbol, args.trend_timeframe, start - trend_warmup, end)

    if entry_raw.empty or trend_raw.empty:
        print("Yeterli veri alinamadi (bos yanit). Tarih araligini kontrol edin.", file=sys.stderr)
        sys.exit(1)

    signal_df = prepare_signal_frame(entry_raw, trend_raw)
    signal_df = signal_df[signal_df["timestamp"] >= start].reset_index(drop=True)

    config = BacktestConfig(starting_balance=args.balance, margin_per_trade=args.margin, leverage=args.leverage)
    result = run_backtest(signal_df, config)

    summary = result["summary"]
    print("\n" + "=" * 72)
    print(f"BACKTEST SONUCU -- {args.symbol} [{start.date()} -> {end.date()}] entry={args.entry_timeframe}")
    print("=" * 72)
    print(f"  Baslangic bakiye     : {_fmt(config.starting_balance)} USDT")
    print(f"  Islem basi marjin    : {_fmt(config.margin_per_trade)} USDT  x{config.leverage} kaldirac")
    print(f"  Toplam islem         : {summary['total_trades']}")
    print(f"  Kazanan / Kaybeden   : {summary['wins']} / {summary['losses']}  (win rate {summary['win_rate_pct']}%)")
    print(f"  Profit factor        : {summary['profit_factor']}")
    print(f"  Son bakiye           : {_fmt(summary['final_balance'])} USDT")
    print(f"  Toplam getiri        : {summary['total_return_pct']}%")
    print(f"  Maksimum drawdown    : {summary['max_drawdown_pct']}%")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tag = f"{args.symbol}_{args.entry_timeframe}_{start.date()}_{end.date()}".replace("/", "-")
    trades_path = os.path.join(OUTPUT_DIR, f"trades_{tag}.csv")
    equity_path = os.path.join(OUTPUT_DIR, f"equity_{tag}.csv")
    result["trades"].to_csv(trades_path, index=False)
    result["equity_curve"].to_csv(equity_path, index=False)
    print(f"\n  Islem gunlugu -> {trades_path}")
    print(f"  Equity egrisi  -> {equity_path}")

    if args.publish:
        path = publish_backtest_result(args, start, end, config, result)
        print(f"  Panele yayinlandi -> {path}")


def publish_backtest_result(args, start, end, config: BacktestConfig, result: dict) -> str:
    """Writes a dashboard-friendly JSON under docs/data/backtests/ and updates the index."""
    os.makedirs(BACKTESTS_DIR, exist_ok=True)
    run_id = f"{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:6]}"
    summary = result["summary"]

    equity_curve = [
        {"timestamp": str(row["timestamp"]), "equity": round(float(row["equity"]), 2)}
        for row in result["equity_curve"].to_dict(orient="records")
    ]
    trades = result["trades"].to_dict(orient="records") if not result["trades"].empty else []
    for t in trades:
        for k in ("entry_time", "exit_time"):
            if k in t:
                t[k] = str(t[k])

    detail = {
        "id": run_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol,
        "entry_timeframe": args.entry_timeframe,
        "trend_timeframe": args.trend_timeframe,
        "start": str(start.date()),
        "end": str(end.date()),
        "config": {
            "starting_balance": config.starting_balance,
            "margin_per_trade": config.margin_per_trade,
            "leverage": config.leverage,
        },
        "summary": summary,
        "equity_curve": equity_curve,
        "trades": trades,
    }
    with open(os.path.join(BACKTESTS_DIR, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(detail, f, indent=2)

    index_path = os.path.join(BACKTESTS_DIR, "index.json")
    index = []
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    index.append({
        "id": run_id,
        "run_at": detail["run_at"],
        "symbol": args.symbol,
        "timeframe": args.entry_timeframe,
        "start": detail["start"],
        "end": detail["end"],
        "total_return_pct": summary["total_return_pct"],
        "total_trades": summary["total_trades"],
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    return os.path.join(BACKTESTS_DIR, f"{run_id}.json")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Guncel BTC/ETH sinyalleri (canli OKX verisiyle)")
    p_analyze.add_argument("--symbols", nargs="+", default=SYMBOLS)
    p_analyze.add_argument("--entry-timeframes", nargs="+", default=ENTRY_TIMEFRAMES, dest="entry_timeframes")
    p_analyze.add_argument("--trend-timeframe", default="1D", dest="trend_timeframe")
    p_analyze.add_argument("--balance", type=float, default=10_000.0)
    p_analyze.add_argument("--margin", type=float, default=500.0)
    p_analyze.add_argument("--leverage", type=float, default=5.0)
    p_analyze.set_defaults(func=cmd_analyze)

    p_bt = sub.add_parser("backtest", help="Gecmis veriyle kaldiracli simulasyon")
    p_bt.add_argument("--symbol", default="BTC-USDT-SWAP")
    p_bt.add_argument("--entry-timeframe", default="4H", dest="entry_timeframe")
    p_bt.add_argument("--trend-timeframe", default="1D", dest="trend_timeframe")
    p_bt.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--end", default=None, help="YYYY-MM-DD (varsayilan: bugun)")
    p_bt.add_argument("--balance", type=float, default=10_000.0)
    p_bt.add_argument("--margin", type=float, default=500.0)
    p_bt.add_argument("--leverage", type=float, default=5.0)
    p_bt.add_argument("--publish", action="store_true", help="Sonucu docs/data/backtests altina yayinla (panelde gorunur)")
    p_bt.set_defaults(func=cmd_backtest)

    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
