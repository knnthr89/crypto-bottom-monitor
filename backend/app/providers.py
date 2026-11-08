import os, requests
from datetime import datetime, timezone

BINANCE="https://data-api.binance.vision"
COINGECKO="https://api.coingecko.com/api/v3"

def binance_daily(symbol, limit=365):
    r=requests.get(f"{BINANCE}/api/v3/klines",params={"symbol":symbol,"interval":"1d","limit":limit},timeout=20)
    r.raise_for_status()
    rows=r.json()
    import pandas as pd
    return pd.DataFrame([{"time":int(x[0]),"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),
        "close":float(x[4]),"volume":float(x[5]),"quote_volume":float(x[7]),
        "taker_buy_quote":float(x[10])} for x in rows])

def coingecko_market_chart(coin_id, days=365):
    key=os.getenv("COINGECKO_API_KEY","")
    headers={"x-cg-demo-api-key":key} if key else {}
    r=requests.get(f"{COINGECKO}/coins/{coin_id}/market_chart",
        params={"vs_currency":"usd","days":days},headers=headers,timeout=30)
    r.raise_for_status()
    return r.json()

def coinglass_spot_cvd(symbol, interval="h4"):
    key=os.getenv("COINGLASS_API_KEY")
    if not key: return None
    r=requests.get("https://open-api-v4.coinglass.com/api/spot/cvd/history",
        params={"symbol":symbol,"interval":interval},
        headers={"CG-API-KEY":key},timeout=25)
    r.raise_for_status()
    payload=r.json()
    return payload.get("data",[])

def google_trends_weekly(keyword, geo=""):
    try:
        from pytrends.request import TrendReq
        client=TrendReq(hl="en-US",tz=0)
        client.build_payload([keyword], timeframe="today 12-m", geo=geo)
        df=client.interest_over_time()
        return df[keyword].tolist() if keyword in df else None
    except Exception:
        return None

def etf_flows_from_csv(asset):
    import pandas as pd
    path=os.getenv("ETF_FLOWS_CSV","./data/etf_flows.csv")
    if not os.path.exists(path): return None
    df=pd.read_csv(path)
    df=df[df.asset.str.upper()==asset]
    return df.sort_values("date").net_flow_usd.tolist() if len(df) else None
