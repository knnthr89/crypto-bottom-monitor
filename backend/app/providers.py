
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
