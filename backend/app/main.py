from fastapi import FastAPI, HTTPException
from datetime import datetime, timezone
from .models import AssetSnapshot, Indicator
from .scoring import Features, score_features
from .store import init, save_row
from .validation import run_validation
from .providers import binance_daily, google_trends_weekly, etf_flows_from_csv, coinglass_spot_cvd_result
from .indicators import trends_score, volume_score, etf_score, cvd_score, price_structure_score
import pandas as pd

app=FastAPI(title="Crypto Bottom Confirmation Monitor",version="0.1.0")
ASSETS={"BTC":("Bitcoin","BTCUSDT","bitcoin"),"ETH":("Ethereum","ETHUSDT","ethereum"),"SOL":("Solana","SOLUSDT","solana")}
@app.on_event("startup")
def startup(): init()

def build_snapshot(asset):
    name,pair,coin=ASSETS[asset]
    caveats=[]
    try:
        candles=binance_daily(pair,limit=180)
        price=float(candles.close.iloc[-1])
        vol=volume_score(candles)
        ps=price_structure_score(candles)
        # Spot CVD is separate from futures CVD; do not silently substitute.
        raw_cvd,cvd_reason=coinglass_spot_cvd_result(pair)
        cvd=None
        if raw_cvd:
            cvd=cvd_score([float(x.get("cum_vol_delta",0)) for x in raw_cvd])
        trends=trends_score(google_trends_weekly(name))
        flows=etf_score(etf_flows_from_csv(asset))
        if flows is None: caveats.append("ETF flow feed not configured or not available for this asset; indicator excluded, not treated as zero.")
        if cvd is None: caveats.append(f"Spot CVD unavailable: {cvd_reason or 'no usable data'}.")
        if trends is None: caveats.append("Google Trends unavailable or throttled; indicator excluded.")
        f=Features(trends,vol,flows,cvd,ps)
        result=score_features(f)
        mode="live_partial"
    except Exception as e:
        price=None; result=score_features(Features()); trends=vol=flows=cvd=ps=None
        caveats.append(f"Provider error: {type(e).__name__}.")
        mode="unavailable"
    maxima={"trends":10,"volume":20,"etf":20,"cvd":20,"price":30}
    labels={"trends":"Google Trends","volume":"Spot volume","etf":"ETF net flows","cvd":"Spot CVD","price":"Price structure"}
    vals={"trends":trends,"volume":vol,"etf":flows,"cvd":cvd,"price":ps}
    details={
      "trends":"Weekly interest recovering from a low base; normalized 0–100 series.",
      "volume":"Looks for capitulation sell-volume followed by expanding up-day spot volume.",
      "etf":"Consistency and magnitude of daily net ETF flows; missing feed is excluded.",
      "cvd":"Spot taker-buy minus taker-sell cumulative delta; exchange universe must stay consistent.",
      "price":"Confirmed daily swing higher-low and higher-high structure."
    }
    indicators=[]
    for k,v in vals.items():
        indicators.append(Indicator(key=k,label=labels[k],score=round(v*maxima[k],1) if v is not None else None,
          maximum=maxima[k],status="available" if v is not None else "missing",detail=details[k]))
    return AssetSnapshot(asset=asset,symbol=pair,price_usd=price,score=result["score"],label=result["label"],
      confirmed_bottom=result["confirmed_bottom"],data_mode=mode,as_of=datetime.now(timezone.utc).isoformat(),
      indicators=indicators,caveats=caveats)

@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/api/v1/assets",response_model=list[AssetSnapshot])
def assets(): return [build_snapshot(a) for a in ASSETS]
@app.get("/api/v1/assets/{asset}",response_model=AssetSnapshot)
def asset(asset:str):
    a=asset.upper()
    if a not in ASSETS: raise HTTPException(404,"Supported assets: BTC, ETH, SOL")
    return build_snapshot(a)
@app.post("/api/v1/validation/run")
def validation(payload:dict):
    a=str(payload.get("asset","BTC")).upper()
    if a not in ASSETS: raise HTTPException(400,"Supported assets: BTC, ETH, SOL")
    return run_validation(a)

@app.post("/api/v1/validation/import")
def import_history(payload:dict):
    """Import pre-aligned, point-in-time daily feature rows for reproducible backtests.
    Each row: date, close, trends, volume, etf, cvd, price_structure (each feature 0..1 or null).
    Values must reflect only information available at that date.
    """
    a=str(payload.get("asset","BTC")).upper()
    if a not in ASSETS: raise HTTPException(400,"Supported assets: BTC, ETH, SOL")
    data=payload.get("rows",[])
    if not data: raise HTTPException(400,"rows is required")
    count=0
    for row in data:
        try:
            f=Features(row.get("trends"),row.get("volume"),row.get("etf"),row.get("cvd"),row.get("price_structure"))
            result=score_features(f)
            save_row(a,str(row["date"]),float(row["close"]),result,row)
            count+=1
        except (KeyError,TypeError,ValueError) as exc:
            raise HTTPException(400,f"Invalid row: {exc}")
    return {"asset":a,"imported":count,"note":"Ensure each feature row is point-in-time and contains no future information."}
