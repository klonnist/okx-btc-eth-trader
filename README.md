# OKX BTC/ETH Teknik Analiz & Backtest Araci

OKX'in genel (public) piyasa verisi API'sini kullanarak BTC-USDT-SWAP ve
ETH-USDT-SWAP icin teknik analiz sinyali ureten ve kaldiracli islemleri
gecmis veri uzerinde simule eden bir arac.

**Bu bir yatirim tavsiyesi degildir ve gercek emir gondermez.** Sadece
genel piyasa verisini okur, kurala dayali bir strateji uygular ve sonuclari
raporlar / simule eder. Nihai karar ve risk kullaniciya aittir.

## Strateji

- **Trend filtresi**: ust zaman diliminde (varsayilan 1D) EMA50 / EMA200
- **Giris tetikleyicisi**: alt zaman diliminde EMA12/EMA26 kesisimi + RSI(14) filtresi, trend ile ayni yonde olmali
- **TP / SL**: ATR(14) bazli -- SL = 1.5x ATR, TP = 2.5x ATR (yaklasik 1:1.67 risk/odul)

## Kurulum

```bash
pip install -r requirements.txt
```

## Kullanim

### Guncel sinyal (canli OKX verisi)

```bash
python cli.py analyze
```

BTC ve ETH icin 15m / 4H / 1D zaman dilimlerinde guncel sinyal, giris/TP/SL ve
onerilen pozisyon buyuklugunu yazdirir.

### Backtest (kaldiracli simulasyon)

```bash
python cli.py backtest --symbol BTC-USDT-SWAP --entry-timeframe 4H \
    --start 2024-01-01 --end 2024-12-31 \
    --balance 10000 --margin 500 --leverage 5
```

- `--balance`: baslangic bakiyesi (USDT)
- `--margin`: islem basi ayrilan marjin (USDT)
- `--leverage`: kaldirac orani
- `--start` / `--end`: backtest tarih araligi (istediginiz araligi filtreleyebilirsiniz)

Sonuclar konsola ozet olarak basilir; ayrintili islem gunlugu ve equity
egrisi `output/` klasorune CSV olarak kaydedilir.

## Onemli notlar / kisitlar

- Fiyat verisi OKX'in genel API'sinden gelir; API anahtari gerekmez, gercek
  emir gonderilmez.
- Backtest motoru basit bir simulasyondur: tek pozisyon, giris/cikis
  komisyonu, ATR bazli TP/SL ve yaklasik likidasyon kontrolu icerir; borsa
  seviyesinde marjin motorunu birebir taklit etmez.
- Gecmis performans gelecegi garanti etmez.
