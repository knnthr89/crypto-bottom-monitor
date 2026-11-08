# Crypto Bottom Confirmation Monitor

Android-first research monitor for BTC, ETH and SOL. This repository contains:
- Android app (Kotlin + Jetpack Compose) that displays asset scores, signal breakdowns and validation summaries.
- FastAPI backend that calculates the five-indicator score and serves asset snapshots.
- Provider adapters for Binance spot candles, CoinGecko market history, Google Trends (optional `pytrends`), CoinGlass spot CVD (API key), and ETF flows via a normalized CSV import.
- Historical validation/backtest engine with chronological, no-look-ahead signal evaluation and 30/60/90-day forward returns.

> This is a research/monitoring tool, not investment advice. A high score is not a guarantee of a market bottom. Provider coverage and licensing vary. Never treat missing data as a positive signal.

## Architecture

`Android app -> FastAPI -> provider adapters -> SQLite (starter) -> scoring + validation`

The starter uses SQLite for easy local deployment. For production, migrate to PostgreSQL/TimescaleDB, add scheduled ingestion, monitoring, secret management, retries, rate-limit handling and provider-specific licensing review.

## Start backend

Python 3.11+:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs`.

The API returns a clearly marked `demo` snapshot when no provider credentials/data are configured. Demo values are synthetic and must never be interpreted as live market readings.

## Provider configuration

- Binance public spot market data: no API key for public market endpoints. Adapter uses `data-api.binance.vision` klines for BTCUSDT, ETHUSDT, SOLUSDT.
- CoinGecko: set `COINGECKO_API_KEY` for your chosen API plan; endpoint/headers can differ by plan.
- CoinGlass: set `COINGLASS_API_KEY`. Spot CVD endpoint access is plan-dependent. Configure exchange/pair per asset in `.env`.
- Google Trends: optional `pytrends`; unofficial interface, may throttle/change. Store the request keyword, geo and retrieval timestamp. Google Trends values are normalized 0–100, not absolute search counts.
- ETF flows: import a normalized CSV using the schema below. BTC/ETH products can be mapped where available. SOL is marked `unavailable` unless a reliable, licensed SOL product-flow source is configured.

CSV columns: `date,asset,net_flow_usd,source`
Example:
`2026-11-06,BTC,125000000,farside-or-licensed-provider`

Do not scrape sites against their terms. Confirm data licensing before commercial use.

## Scoring model (0–100)

| Indicator | Max |
|---|---:|
| Google Trends recovery | 10 |
| Spot volume / capitulation then demand | 20 |
| ETF net flows | 20 |
| Spot CVD | 20 |
| Price structure | 30 |

Weights are versioned in `backend/app/scoring.py`. A raw total alone cannot declare a confirmed bottom:
- Price structure must score 30 (confirmed higher low then confirmed higher high).
- At least two of Trends, volume, ETF flows and spot CVD must be positive (>= 50% of their weight).
- Minimum overall score: 70.
- Otherwise the label is `not_confirmed`, `early_accumulation` or `recovery_developing`.

Swing pivots use only closed daily candles. A pivot is confirmed after `PIVOT_RIGHT` subsequent candles; the confirmation date is used, not the pivot date, preventing look-ahead leakage.

## Historical validation

`POST /api/v1/validation/run` runs chronological evaluation over stored daily feature rows and reports:
- signal count and coverage
- 30/60/90-day forward returns
- hit rate (forward return > 0)
- mean and median forward return

For a valid study, load a complete daily dataset for each asset and each indicator, include missingness, freeze scoring rules before testing, use walk-forward splits, compare to buy-and-hold and random/baseline signals, and include fees/slippage. Historical cycle examples such as Dec 2018, Mar 2020 and Nov 2022 are useful case studies but not a statistically sufficient sample.

## Android

Open `android/` in Android Studio (AGP 8.7+, Kotlin 2.0+, JDK 17). Set `BASE_URL` in `app/build.gradle.kts` to your backend:
- Emulator: `http://10.0.2.2:8000/`
- Physical phone: `http://YOUR_COMPUTER_LAN_IP:8000/`

The starter UI polls the API on refresh. For production, use HTTPS, WorkManager, paging, charts, offline cache and push notifications.

## Important limitations

1. ETF flow feeds are not equally available for all assets. Do not infer SOL flows from BTC/ETH.
2. CVD is exchange/pair-dependent; aggregated CVD needs a consistent, documented exchange universe.
3. Volume is not directional by itself. The engine combines capitulation-volume context with subsequent up-day demand.
4. Trends is delayed/normalized and may be sparse for smaller assets.
5. A higher-low/higher-high rule is timeframe-dependent. This starter uses daily bars and configurable pivot windows.
6. No credentials or live data are bundled. The first run is in demo mode until data providers are configured and ingested.
