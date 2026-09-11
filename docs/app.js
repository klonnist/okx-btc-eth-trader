const PROFILES = ["15m", "4h", "1d"];
let activeTab = "15m";

function fmtUsd(n, withSign) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = withSign && n > 0 ? "+" : "";
  return sign + Number(n).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " USDT";
}

function fmtPrice(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function pnlClass(n) {
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function fetchJson(path) {
  const res = await fetch(path + "?_=" + Date.now());
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function renderCards(state) {
  const openPositions = Object.values(state.open_positions || {});
  const unrealized = state.stats.unrealized_pnl || 0;
  const cards = [
    ["Bakiye", fmtUsd(state.balance)],
    ["Toplam K/Z", fmtUsd(state.stats.total_pnl, true), pnlClass(state.stats.total_pnl)],
    ["Anlık K/Z", fmtUsd(unrealized, true), pnlClass(unrealized)],
    ["Kazanma Oranı", `%${state.stats.win_rate_pct}`],
    ["Toplam İşlem", state.stats.total_trades],
    ["Açık Pozisyon", openPositions.length],
    ["Kaldıraç", `${state.leverage}x`],
    ["Marjin / İşlem", fmtUsd(state.margin_per_trade)],
  ];
  document.getElementById("cards").innerHTML = cards.map(([label, value, cls]) => `
    <div class="card">
      <div class="label">${label}</div>
      <div class="value ${cls || ""}">${value}</div>
    </div>`).join("");
}

function renderPositions(state) {
  const rows = Object.values(state.open_positions || {});
  const wrap = document.getElementById("positions-wrap");
  if (!rows.length) {
    wrap.innerHTML = `<div class="empty">Şu an açık pozisyon yok.</div>`;
    return;
  }
  wrap.innerHTML = `<table>
    <thead><tr>
      <th>Sembol</th><th>Yön</th><th>Giriş</th><th>Anlık Fiyat</th><th>Anlık K/Z</th>
      <th>Anlık R</th><th>TP</th><th>SL</th><th>Kaldıraç</th><th>Margin</th><th>Açılış</th>
    </tr></thead>
    <tbody>
      ${rows.map(p => `<tr>
        <td>${p.symbol}</td>
        <td class="${p.side === "BUY" ? "side-buy" : "side-sell"}">${p.side}</td>
        <td>${fmtPrice(p.entry_price)}</td>
        <td>${fmtPrice(p.last_price)}</td>
        <td class="${pnlClass(p.unrealized_pnl)}">${fmtUsd(p.unrealized_pnl, true)}</td>
        <td class="${pnlClass(p.unrealized_r)}">${p.unrealized_r}</td>
        <td>${fmtPrice(p.tp)}</td>
        <td>${fmtPrice(p.sl)}</td>
        <td>${p.leverage}x</td>
        <td>${fmtUsd(p.margin)}</td>
        <td>${fmtTime(p.opened_at)}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

function renderTrades(state) {
  const rows = (state.closed_trades || []).slice(-15).reverse();
  const wrap = document.getElementById("trades-wrap");
  if (!rows.length) {
    wrap.innerHTML = `<div class="empty">Henüz kapanmış işlem yok.</div>`;
    return;
  }
  wrap.innerHTML = `<table>
    <thead><tr>
      <th>Sembol</th><th>Yön</th><th>Giriş</th><th>Çıkış</th><th>Sonuç</th><th>K/Z</th><th>Kapanış</th>
    </tr></thead>
    <tbody>
      ${rows.map(t => `<tr>
        <td>${t.symbol}</td>
        <td class="${t.side === "BUY" ? "side-buy" : "side-sell"}">${t.side}</td>
        <td>${fmtPrice(t.entry_price)}</td>
        <td>${fmtPrice(t.exit_price)}</td>
        <td><span class="badge">${t.exit_reason}</span></td>
        <td class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl, true)}</td>
        <td>${fmtTime(t.exit_time)}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

async function loadProfile(profile) {
  document.getElementById("account-view").style.display = "";
  document.getElementById("backtest-view").style.display = "none";
  try {
    const state = await fetchJson(`data/${profile}/state.json`);
    renderCards(state);
    renderPositions(state);
    renderTrades(state);
    document.getElementById("updated").textContent = "Son güncelleme: " + fmtTime(state.last_updated);
  } catch (e) {
    document.getElementById("cards").innerHTML = "";
    document.getElementById("positions-wrap").innerHTML =
      `<div class="empty">Bu profil için henüz veri yok (ilk çalıştırma bekleniyor).</div>`;
    document.getElementById("trades-wrap").innerHTML = "";
  }
}

function sparklineSvg(points) {
  if (!points.length) return "";
  const w = 760, h = 160, pad = 8;
  const values = points.map(p => p.equity);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const stepX = (w - pad * 2) / Math.max(points.length - 1, 1);
  const coords = values.map((v, i) => {
    const x = pad + i * stepX;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const up = values[values.length - 1] >= values[0];
  const color = up ? "#3ddc84" : "#ff5c5c";
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
    <polyline fill="none" stroke="${color}" stroke-width="2" points="${coords.join(" ")}" />
  </svg>`;
}

function renderDetailHtml(detail) {
  const s = detail.summary;
  return `
    <div class="cards">
      <div class="card"><div class="label">Sembol</div><div class="value">${detail.symbol}</div></div>
      <div class="card"><div class="label">Zaman Dilimi</div><div class="value">${detail.entry_timeframe}</div></div>
      <div class="card"><div class="label">Kaldıraç</div><div class="value">${detail.config.leverage}x</div></div>
      <div class="card"><div class="label">Toplam Getiri</div><div class="value ${pnlClass(s.total_return_pct)}">%${s.total_return_pct}</div></div>
      <div class="card"><div class="label">Kazanma Oranı</div><div class="value">%${s.win_rate_pct}</div></div>
      <div class="card"><div class="label">Max Drawdown</div><div class="value neg">%${s.max_drawdown_pct}</div></div>
    </div>
    <div class="panel">
      <h2>Equity Eğrisi (${detail.start} → ${detail.end})</h2>
      <div style="padding:10px 14px;">${sparklineSvg(detail.equity_curve)}</div>
    </div>
    <div class="panel" style="margin-top:14px;">
      <h2>İşlemler (${detail.trades.length})</h2>
      <div>
        ${detail.trades.length ? `<table>
          <thead><tr><th>Yön</th><th>Giriş</th><th>Çıkış</th><th>Sonuç</th><th>K/Z</th><th>Kapanış</th></tr></thead>
          <tbody>${detail.trades.map(t => `<tr>
            <td class="${t.side === "BUY" ? "side-buy" : "side-sell"}">${t.side}</td>
            <td>${fmtPrice(t.entry_price)}</td>
            <td>${fmtPrice(t.exit_price)}</td>
            <td><span class="badge">${t.exit_reason}</span></td>
            <td class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl, true)}</td>
            <td>${fmtTime(t.exit_time)}</td>
          </tr>`).join("")}</tbody>
        </table>` : `<div class="empty">Bu aralıkta işlem açılmadı.</div>`}
      </div>
    </div>`;
}

async function loadBacktestDetail(id) {
  const result = document.getElementById("bt-result");
  result.innerHTML = `<div class="panel"><div class="empty">Yükleniyor…</div></div>`;
  result.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const detail = await fetchJson(`data/backtests/${id}.json`);
    result.innerHTML = renderDetailHtml(detail);
  } catch (e) {
    result.innerHTML = `<div class="error-box">Sonuç yüklenemedi: ${e.message}</div>`;
  }
}

async function loadBacktestHistory() {
  const wrap = document.getElementById("bt-history");
  wrap.innerHTML = `<div class="panel"><div class="empty">Yükleniyor…</div></div>`;
  try {
    const index = await fetchJson("data/backtests/index.json");
    if (!index.length) throw new Error("empty");
    wrap.innerHTML = `<div class="panel">
      <h2>Geçmiş Backtest Çalıştırmaları (GitHub Actions üzerinden yayınlanan)</h2>
      <div>
        <table>
          <thead><tr><th>Tarih</th><th>Sembol</th><th>Zaman Dilimi</th><th>Aralık</th><th>Getiri</th><th>İşlem</th><th></th></tr></thead>
          <tbody>
            ${index.slice().reverse().map(r => `<tr>
              <td>${fmtTime(r.run_at)}</td>
              <td>${r.symbol}</td>
              <td>${r.timeframe}</td>
              <td>${r.start} → ${r.end}</td>
              <td class="${pnlClass(r.total_return_pct)}">%${r.total_return_pct}</td>
              <td>${r.total_trades}</td>
              <td><button class="tab-btn detail-btn" data-id="${r.id}">Detay</button></td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
    wrap.querySelectorAll(".detail-btn").forEach(btn => {
      btn.addEventListener("click", () => loadBacktestDetail(btn.dataset.id));
    });
  } catch (e) {
    wrap.innerHTML = "";
  }
}

function dateInputToMs(value, endOfDay) {
  const [y, m, d] = value.split("-").map(Number);
  return endOfDay ? Date.UTC(y, m - 1, d, 23, 59, 59, 999) : Date.UTC(y, m - 1, d, 0, 0, 0, 0);
}

function setupBacktestForm() {
  const form = document.getElementById("bt-form");
  const endInput = form.querySelector("[name=end]");
  const startInput = form.querySelector("[name=start]");
  const today = new Date();
  endInput.value = today.toISOString().slice(0, 10);
  const ninetyDaysAgo = new Date(today.getTime() - 90 * 86_400_000);
  startInput.value = ninetyDaysAgo.toISOString().slice(0, 10);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const symbol = fd.get("symbol");
    const timeframe = fd.get("timeframe");
    const startMs = dateInputToMs(fd.get("start"), false);
    const endVal = fd.get("end");
    const endMs = endVal ? dateInputToMs(endVal, true) : Date.now();
    const balance = Number(fd.get("balance"));
    const margin = Number(fd.get("margin"));
    const leverage = Number(fd.get("leverage"));

    const result = document.getElementById("bt-result");
    const btn = form.querySelector(".run-btn");
    if (startMs >= endMs) {
      result.innerHTML = `<div class="error-box">Başlangıç tarihi bitiş tarihinden önce olmalı.</div>`;
      return;
    }
    btn.disabled = true;
    btn.textContent = "Çalışıyor…";
    result.innerHTML = `<div class="panel"><div class="empty">OKX'ten veri çekiliyor ve backtest hesaplanıyor…</div></div>`;
    try {
      const detail = await runClientBacktest({
        symbol, entryTimeframe: timeframe, startMs, endMs,
        startingBalance: balance, marginPerTrade: margin, leverage,
      });
      result.innerHTML = renderDetailHtml(detail);
    } catch (err) {
      result.innerHTML = `<div class="error-box">Backtest başarısız: ${err.message}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "▶ Çalıştır";
    }
  });
}

function setActiveTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn[data-tab]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.getElementById("account-view").style.display = tab === "backtest" ? "none" : "";
  document.getElementById("backtest-view").style.display = tab === "backtest" ? "" : "none";
  if (tab === "backtest") {
    loadBacktestHistory();
  } else {
    loadProfile(tab);
  }
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab-btn");
  if (btn && btn.dataset.tab) setActiveTab(btn.dataset.tab);
});

setupBacktestForm();
setActiveTab("15m");
setInterval(() => { if (activeTab !== "backtest") setActiveTab(activeTab); }, 60_000);
