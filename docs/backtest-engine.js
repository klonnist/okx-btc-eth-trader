/* Client-side port of okx_trader/{okx_client,indicators,strategy,backtest}.py
 * so the dashboard can run an ad-hoc backtest directly in the visitor's
 * browser (OKX's public market-data API allows cross-origin requests).
 * No API key, no server -- just reads public candle data.
 */
const OKX_BASE = "https://www.okx.com";

const BAR_MS = {
  "1m": 60_000, "3m": 3 * 60_000, "5m": 5 * 60_000, "15m": 15 * 60_000, "30m": 30 * 60_000,
  "1H": 3_600_000, "2H": 2 * 3_600_000, "4H": 4 * 3_600_000, "6H": 6 * 3_600_000, "12H": 12 * 3_600_000,
  "1D": 86_400_000, "1W": 7 * 86_400_000,
};

const STRAT = {
  TREND_EMA_FAST: 50, TREND_EMA_SLOW: 200,
  ENTRY_EMA_FAST: 12, ENTRY_EMA_SLOW: 26,
  RSI_PERIOD: 14, ATR_PERIOD: 14,
  RSI_LONG: [35, 70], RSI_SHORT: [30, 65],
  SL_ATR_MULT: 1.5, TP_ATR_MULT: 2.5,
};

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function fetchHistoryCandles(instId, bar, startMs, endMs, pause = 150) {
  const rows = [];
  const seen = new Set();
  let after = null;
  while (true) {
    const params = new URLSearchParams({ instId, bar, limit: "100" });
    if (after !== null) params.set("after", String(after));
    const res = await fetch(`${OKX_BASE}/api/v5/market/history-candles?${params}`);
    const payload = await res.json();
    if (payload.code !== "0") throw new Error(`OKX API hatasi: ${payload.msg || payload.code}`);
    const batch = payload.data;
    if (!batch || !batch.length) break;

    const fresh = batch.filter(r => !seen.has(r[0]));
    if (!fresh.length) break;
    fresh.forEach(r => seen.add(r[0]));
    rows.push(...fresh);

    const oldestTs = Math.min(...batch.map(r => Number(r[0])));
    after = oldestTs;
    if (oldestTs <= startMs) break;
    await sleep(pause);
  }

  const candles = rows
    .map(r => ({
      timestamp: Number(r[0]), open: Number(r[1]), high: Number(r[2]),
      low: Number(r[3]), close: Number(r[4]), volume: Number(r[5]),
    }))
    .filter(c => c.timestamp >= startMs && c.timestamp <= endMs)
    .sort((a, b) => a.timestamp - b.timestamp);
  return candles;
}

function ema(values, span) {
  const k = 2 / (span + 1);
  const out = new Array(values.length);
  out[0] = values[0];
  for (let i = 1; i < values.length; i++) out[i] = values[i] * k + out[i - 1] * (1 - k);
  return out;
}

function rsi(closes, period) {
  const out = new Array(closes.length).fill(50);
  let avgGain = null, avgLoss = null;
  for (let i = 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain = Math.max(delta, 0), loss = Math.max(-delta, 0);
    if (avgGain === null) { avgGain = gain; avgLoss = loss; }
    else {
      avgGain = gain / period + avgGain * (1 - 1 / period);
      avgLoss = loss / period + avgLoss * (1 - 1 / period);
    }
    if (i >= period) {
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }
  return out;
}

function atr(candles, period) {
  const out = new Array(candles.length).fill(null);
  let prevAtr = null;
  for (let i = 0; i < candles.length; i++) {
    const { high, low, close } = candles[i];
    const prevClose = i > 0 ? candles[i - 1].close : close;
    const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
    if (prevAtr === null) prevAtr = tr;
    else prevAtr = tr / period + prevAtr * (1 - 1 / period);
    out[i] = prevAtr;
  }
  return out;
}

function buildTrendSeries(candles) {
  const closes = candles.map(c => c.close);
  const emaFast = ema(closes, STRAT.TREND_EMA_FAST);
  const emaSlow = ema(closes, STRAT.TREND_EMA_SLOW);
  return candles.map((c, i) => {
    let trend = "neutral";
    if (emaFast[i] > emaSlow[i] && c.close > emaSlow[i]) trend = "up";
    else if (emaFast[i] < emaSlow[i] && c.close < emaSlow[i]) trend = "down";
    return { timestamp: c.timestamp, trend };
  });
}

function buildEntrySeries(candles) {
  const closes = candles.map(c => c.close);
  const emaFast = ema(closes, STRAT.ENTRY_EMA_FAST);
  const emaSlow = ema(closes, STRAT.ENTRY_EMA_SLOW);
  const rsiVals = rsi(closes, STRAT.RSI_PERIOD);
  const atrVals = atr(candles, STRAT.ATR_PERIOD);
  return candles.map((c, i) => ({
    ...c, emaFast: emaFast[i], emaSlow: emaSlow[i], rsi: rsiVals[i], atr: atrVals[i],
  }));
}

function attachTrendAndSignals(entrySeries, trendSeries) {
  let ti = 0;
  let prevFast = null, prevSlow = null;
  return entrySeries.map(row => {
    while (ti + 1 < trendSeries.length && trendSeries[ti + 1].timestamp <= row.timestamp) ti++;
    const trend = trendSeries[ti] && trendSeries[ti].timestamp <= row.timestamp ? trendSeries[ti].trend : "neutral";

    let signal = "NONE";
    if (prevFast !== null) {
      const crossUp = prevFast <= prevSlow && row.emaFast > row.emaSlow;
      const crossDown = prevFast >= prevSlow && row.emaFast < row.emaSlow;
      const rsiOkLong = row.rsi >= STRAT.RSI_LONG[0] && row.rsi <= STRAT.RSI_LONG[1];
      const rsiOkShort = row.rsi >= STRAT.RSI_SHORT[0] && row.rsi <= STRAT.RSI_SHORT[1];
      if (crossUp && trend === "up" && rsiOkLong) signal = "BUY";
      else if (crossDown && trend === "down" && rsiOkShort) signal = "SELL";
    }
    prevFast = row.emaFast; prevSlow = row.emaSlow;
    return { ...row, trend, signal };
  });
}

function computeTpSl(entryPrice, atrValue, side) {
  if (side === "BUY") {
    return [entryPrice - STRAT.SL_ATR_MULT * atrValue, entryPrice + STRAT.TP_ATR_MULT * atrValue];
  }
  return [entryPrice + STRAT.SL_ATR_MULT * atrValue, entryPrice - STRAT.TP_ATR_MULT * atrValue];
}

function liquidationPrice(entryPrice, leverage, side) {
  return side === "BUY" ? entryPrice * (1 - 1 / leverage) : entryPrice * (1 + 1 / leverage);
}

function runBacktest(rows, { startingBalance, marginPerTrade, leverage, feeRate = 0.0005 }) {
  let balance = startingBalance;
  let position = null;
  const trades = [];
  const equityCurve = [];

  for (const row of rows) {
    const { timestamp, high, low, close } = row;

    if (position) {
      const liq = liquidationPrice(position.entryPrice, leverage, position.side);
      let exitPrice = null, reason = null;
      if (position.side === "BUY") {
        if (low <= liq) { exitPrice = liq; reason = "LIQUIDATION"; }
        else if (low <= position.sl) { exitPrice = position.sl; reason = "SL"; }
        else if (high >= position.tp) { exitPrice = position.tp; reason = "TP"; }
      } else {
        if (high >= liq) { exitPrice = liq; reason = "LIQUIDATION"; }
        else if (high >= position.sl) { exitPrice = position.sl; reason = "SL"; }
        else if (low <= position.tp) { exitPrice = position.tp; reason = "TP"; }
      }
      if (exitPrice !== null) {
        const gross = position.side === "BUY"
          ? (exitPrice - position.entryPrice) * position.qty
          : (position.entryPrice - exitPrice) * position.qty;
        const exitFee = exitPrice * position.qty * feeRate;
        const pnl = Math.max(gross - exitFee, -position.margin);
        balance += pnl;
        trades.push({
          side: position.side, entry_time: position.entryTime, entry_price: position.entryPrice,
          exit_time: timestamp, exit_price: exitPrice, exit_reason: reason,
          pnl, balance_after: balance,
        });
        position = null;
      }
    }

    if (!position && (row.signal === "BUY" || row.signal === "SELL") && balance >= marginPerTrade) {
      const [sl, tp] = computeTpSl(close, row.atr, row.signal);
      const notional = marginPerTrade * leverage;
      const qty = notional / close;
      balance -= notional * feeRate;
      position = { side: row.signal, entryTime: timestamp, entryPrice: close, sl, tp, qty, margin: marginPerTrade };
    }

    let unrealized = 0;
    if (position) {
      unrealized = position.side === "BUY"
        ? (close - position.entryPrice) * position.qty
        : (position.entryPrice - close) * position.qty;
    }
    equityCurve.push({ timestamp, equity: balance + unrealized });
  }

  const summary = summarize(trades, equityCurve, startingBalance);
  return { trades, equityCurve, summary };
}

function summarize(trades, equityCurve, startingBalance) {
  if (!trades.length) {
    return { total_trades: 0, wins: 0, losses: 0, win_rate_pct: 0, final_balance: startingBalance, total_return_pct: 0, max_drawdown_pct: 0, profit_factor: null };
  }
  const wins = trades.filter(t => t.pnl > 0);
  const losses = trades.filter(t => t.pnl <= 0);
  const finalBalance = trades[trades.length - 1].balance_after;

  let peak = -Infinity, maxDd = 0;
  for (const p of equityCurve) {
    peak = Math.max(peak, p.equity);
    maxDd = Math.min(maxDd, (p.equity - peak) / peak);
  }
  const grossProfit = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));

  return {
    total_trades: trades.length,
    wins: wins.length,
    losses: losses.length,
    win_rate_pct: Math.round((wins.length / trades.length) * 10000) / 100,
    final_balance: Math.round(finalBalance * 100) / 100,
    total_return_pct: Math.round(((finalBalance - startingBalance) / startingBalance) * 10000) / 100,
    max_drawdown_pct: Math.round(maxDd * 10000) / 100,
    profit_factor: grossLoss > 0 ? Math.round((grossProfit / grossLoss) * 100) / 100 : null,
  };
}

async function runClientBacktest({ symbol, entryTimeframe, trendTimeframe = "1D", startMs, endMs, startingBalance, marginPerTrade, leverage }) {
  const entryWarmup = BAR_MS[entryTimeframe] * 300;
  const trendWarmup = BAR_MS["1D"] * 400;

  const [entryRaw, trendRaw] = await Promise.all([
    fetchHistoryCandles(symbol, entryTimeframe, startMs - entryWarmup, endMs),
    fetchHistoryCandles(symbol, trendTimeframe, startMs - trendWarmup, endMs),
  ]);
  if (!entryRaw.length || !trendRaw.length) throw new Error("Yeterli veri alinamadi.");

  const trendSeries = buildTrendSeries(trendRaw);
  const entrySeries = buildEntrySeries(entryRaw);
  const signalRows = attachTrendAndSignals(entrySeries, trendSeries).filter(r => r.timestamp >= startMs);

  const result = runBacktest(signalRows, { startingBalance, marginPerTrade, leverage });
  return {
    symbol, entry_timeframe: entryTimeframe,
    start: new Date(startMs).toISOString().slice(0, 10),
    end: new Date(endMs).toISOString().slice(0, 10),
    config: { starting_balance: startingBalance, margin_per_trade: marginPerTrade, leverage },
    summary: result.summary,
    equity_curve: result.equityCurve.map(p => ({ timestamp: new Date(p.timestamp).toISOString(), equity: p.equity })),
    trades: result.trades.map(t => ({
      side: t.side, entry_price: t.entry_price, exit_price: t.exit_price, exit_reason: t.exit_reason,
      pnl: t.pnl, exit_time: new Date(t.exit_time).toISOString(),
    })),
  };
}
