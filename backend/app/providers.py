
import os
import requests
import pandas as pd

BINANCE = "https://data-api.binance.vision"
COINGECKO = "https://api.coingecko.com/api/v3"
CRYPTOETF_API = "https://api.cryptoetf.today/api/v1"

def binance_daily(symbol, limit=365):
    r = requests.get(
        f"{BINANCE}/api/v3/klines",
        params={"symbol": symbol, "interval": "1d", "limit": limit},
        timeout=20
    )
    r.raise_for_status()
    rows = r.json()
    return pd.DataFrame([{
        "time": int(x[0]),
        "open": float(x[1]),
        "high": float(x[2]),
        "low": float(x[3]),
        "close": float(x[4]),
        "volume": float(x[5]),
        "quote_volume": float(x[7]),
        "taker_buy_quote": float(x[10])
    } for x in rows])

def coingecko_market_chart(coin_id, days=365):
    key = os.getenv("COINGECKO_API_KEY", "")
    headers = {"x-cg-demo-api-key": key} if key else {}
    r = requests.get(
        f"{COINGECKO}/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": days},
        headers=headers,
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def coinglass_spot_cvd_result(symbol, interval="4h"):
    """Return (data, reason); missing plan access triggers the Binance proxy."""
    key = os.getenv("COINGLASS_API_KEY")
    if not key:
        return None, "COINGLASS_API_KEY is not set in the backend environment"

    try:
        r = requests.get(
            "https://open-api-v4.coinglass.com/api/spot/cvd/history",
            params={
                "exchange": "Binance",
                "symbol": symbol,
                "interval": interval
            },
            headers={"CG-API-KEY": key},
            timeout=20
        )
    except requests.RequestException as e:
        return None, f"CoinGlass request failed: {type(e).__name__}"

    try:
        payload = r.json()
    except ValueError:
        payload = {}

    if r.status_code != 200:
        return None, f"CoinGlass HTTP {r.status_code}: {str(payload.get('msg') or r.text)[:120]}"

    code = str(payload.get("code", "0"))
    if code not in ("0", "200"):
        return None, f"CoinGlass error code {code}: {str(payload.get('msg', ''))[:120]}"

    data = payload.get("data") or []
    if not data:
        return None, "CoinGlass returned no spot CVD data for this symbol"

    return data, None

def coinglass_spot_cvd(symbol, interval="4h"):
    return coinglass_spot_cvd_result(symbol, interval)[0]

def google_trends_weekly(keyword, geo=""):
    try:
        from pytrends.request import TrendReq
        client = TrendReq(hl="en-US", tz=0)
        client.build_payload([keyword], timeframe="today 12-m", geo=geo)
        df = client.interest_over_time()
        return df[keyword].tolist() if keyword in df else None
    except Exception:
        return None

def etf_flows_from_csv(asset):
    """Legacy CSV fallback."""
    path = os.getenv("ETF_FLOWS_CSV", "./data/etf_flows.csv")
    if not os.path.exists(path):
        return None

    df = pd.read_csv(path)
    df = df[df.asset.str.upper() == asset]
    return df.sort_values("date").net_flow_usd.tolist() if len(df) else None

def _complete_etf_flows(payload):
    """
    Convert CryptoETF daily fund-level flows from USD millions to USD.
    Exclude days where any fund has an unreported flow.
    """
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]

    if not isinstance(payload, dict):
        return []

    days = payload.get("days") or []
    complete = []

    for day in days:
        funds = day.get("funds") or []

        if not funds:
            continue

        values = [fund.get("netFlowUsdM") for fund in funds]

        # A missing fund figure is not the same as zero.
        if any(value is None for value in values):
            continue

        try:
            total_usd = sum(float(value) for value in values) * 1_000_000
        except (TypeError, ValueError):
            continue

        complete.append({
            "date": day.get("date", ""),
            "net_flow_usd": total_usd
        })

    complete.sort(key=lambda item: item["date"])
    return [item["net_flow_usd"] for item in complete]

def etf_flows_result(asset):
    """
    Return (flows, reason).
    Uses CryptoETF when an API key is configured.
    Falls back to the legacy CSV when no API key is configured.
    """
    asset_slugs = {
        "BTC": "btc",
        "ETH": "eth",
        "SOL": "sol"
    }

    asset = asset.upper()
    slug = asset_slugs.get(asset)

    if not slug:
        return None, f"Unsupported ETF asset: {asset}"

    key = os.getenv("CRYPTOETF_API_KEY") or os.getenv("CRYPTOETF_KEY")

    if not key:
        csv_flows = etf_flows_from_csv(asset)
        if csv_flows:
            return csv_flows, "Using legacy CSV ETF data; CryptoETF API key is not configured"
        return None, "CRYPTOETF_API_KEY is not configured and no CSV ETF data is available"

    try:
        r = requests.get(
            f"{CRYPTOETF_API}/flows/{slug}/funds",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20
        )
    except requests.RequestException as e:
        return None, f"CryptoETF request failed: {type(e).__name__}"

    if r.status_code == 401:
        return None, "CryptoETF API rejected the key (HTTP 401)"

    if r.status_code == 429:
        return None, "CryptoETF rate limit reached (HTTP 429)"

    if r.status_code != 200:
        return None, f"CryptoETF API returned HTTP {r.status_code}"

    try:
        payload = r.json()
    except ValueError:
        return None, "CryptoETF returned invalid JSON"

    flows = _complete_etf_flows(payload)

    if not flows:
        return None, "CryptoETF returned no complete daily fund-flow data"

    if len(flows) < 10:
        return None, f"Only {len(flows)} complete ETF flow days available; at least 10 are required"

    return flows, None

def coinglass_derivatives_result(asset):
    """Aggregate Hobbyist-compatible CoinGlass futures OI and pairs-market metrics."""
    key = os.getenv("COINGLASS_API_KEY")
    if not key:
        return None, "COINGLASS_API_KEY is not set"

    headers = {"CG-API-KEY": key}
    symbol = asset.upper()
    base = "https://open-api-v4.coinglass.com"

    def get_json(path, params):
        response = requests.get(f"{base}{path}", params=params, headers=headers, timeout=20)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200:
            raise RuntimeError(f"CoinGlass HTTP {response.status_code}")
        if str(payload.get("code", "0")) not in ("0", "200"):
            raise RuntimeError(f"CoinGlass API error: {str(payload.get('msg', 'unknown'))[:100]}")
        return payload.get("data")

    try:
        oi_data = get_json(
            "/api/futures/open-interest/aggregated-history",
            {"symbol": symbol, "interval": "4h", "limit": 7, "unit": "usd"}
        ) or []
        pairs_data = get_json(
            "/api/futures/pairs-markets",
            {"symbol": symbol}
        ) or []

        # Sum exchange-level values for the requested coin.
        oi_values = []
        volume = long_liq = short_liq = 0.0
        funding_weighted = funding_weight = 0.0
        change_weighted = change_weight = 0.0
        for row in pairs_data:
            if not isinstance(row, dict):
                continue
            pair_symbol = str(row.get("symbol", "")).upper()
            instrument = str(row.get("instrument_id", "")).upper()
            if symbol not in pair_symbol and not instrument.startswith(symbol):
                continue

            oi = float(row.get("open_interest_usd") or 0)
            volume += float(row.get("volume_usd") or 0)
            long_liq += float(row.get("long_liquidation_usd_24h") or 0)
            short_liq += float(row.get("short_liquidation_usd_24h") or 0)

            funding = row.get("funding_rate")
            if funding is not None and oi > 0:
                funding_weighted += float(funding) * oi
                funding_weight += oi

            change = row.get("open_interest_change_percent_24h")
            if change is not None and oi > 0:
                change_weighted += float(change) * oi
                change_weight += oi

        closes = []
        for point in oi_data:
            if isinstance(point, dict) and point.get("close") is not None:
                closes.append(float(point["close"]))

        oi_change_history = None
        if len(closes) >= 2 and closes[0] != 0:
            oi_change_history = (closes[-1] / closes[0] - 1) * 100

        result = {
            "open_interest_usd": sum(float(row.get("open_interest_usd") or 0) for row in pairs_data
                                     if isinstance(row, dict)
                                     and (symbol in str(row.get("symbol", "")).upper()
                                          or str(row.get("instrument_id", "")).upper().startswith(symbol))),
            "open_interest_24h_change_pct": change_weighted / change_weight if change_weight else None,
            "open_interest_4h_history_change_pct": oi_change_history,
            "funding_rate": funding_weighted / funding_weight if funding_weight else None,
            "long_liquidations_24h_usd": long_liq,
            "short_liquidations_24h_usd": short_liq,
            "futures_volume_24h_usd": volume,
            "oi_history_points": len(closes),
            "pairs_count": len(pairs_data)
        }
        if not result["open_interest_usd"] and not closes:
            return None, f"CoinGlass returned no usable futures data for {symbol}"
        return result, None
    except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
        return None, f"CoinGlass derivatives unavailable: {str(exc)[:140]}"
