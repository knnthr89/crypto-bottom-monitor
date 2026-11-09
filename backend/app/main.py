from fastapi import FastAPI, HTTPException, Query
from datetime import datetime, timezone
from .models import AssetSnapshot, Indicator
from .scoring import Features, score_features
from .store import init, save_row, history_rows
from .validation import run_validation
from .providers import binance_daily, google_trends_weekly, etf_flows_result, coinglass_spot_cvd_result, coinglass_derivatives_result
from .indicators import trends_score, volume_score, etf_score, cvd_score, price_structure_score
from .backfill import backfill_btc_history
from .backtest import run_btc_backtest

app=FastAPI(title="Crypto Bottom Confirmation Monitor",version="0.2.0")
ASSETS={"BTC":("Bitcoin","BTCUSDT","bitcoin"),"ETH":("Ethereum","ETHUSDT","ethereum"),"SOL":("Solana","SOLUSDT","solana")}

@app.on_event("startup")
def startup():
    init()

def build_snapshot(asset):
    name,pair,coin=ASSETS[asset]
    caveats=[]
    try:
        candles=binance_daily(pair,limit=180)
        if candles.empty:
            raise RuntimeError("Binance returned no daily candles")
        price=float(candles.close.iloc[-1])
        vol=volume_score(candles)
        ps=price_structure_score(candles)

        # Prefer CoinGlass spot CVD when the subscribed plan exposes it.
        raw_cvd,cvd_reason=coinglass_spot_cvd_result(pair)
        cvd=None
        flow_label="Spot CVD"
        flow_detail="Spot cumulative volume delta from CoinGlass; exchange/pair coverage depends on subscription."
        if raw_cvd:
            values=[]
            for point in raw_cvd:
                value=point.get("cum_vol_delta")
                if value is None:
                    value=point.get("cvd")
                if value is not None:
                    values.append(float(value))
            cvd=cvd_score(values) if values else None

        # Binance klines expose taker-buy quote volume, so derive a clearly-labelled proxy.
        if cvd is None:
            daily_delta=(2*candles.taker_buy_quote-candles.quote_volume).fillna(0)
            cvd=cvd_score(daily_delta.cumsum().tolist())
            flow_label="Spot taker flow (proxy)"
            flow_detail="Binance spot proxy: cumulative taker-buy quote volume minus estimated taker-sell quote volume. Not true aggregated CVD."
            caveats.append("CoinGlass spot CVD unavailable; using Binance spot taker-buy/sell volume as a directional proxy, not true aggregated CVD.")

        trends=trends_score(google_trends_weekly(name))

        raw_etf_flows, etf_reason = etf_flows_result(asset)
        flows = etf_score(raw_etf_flows)

        if flows is None:
            caveats.append(
                f"ETF flow indicator unavailable: {etf_reason or 'insufficient data'}."
            )
        elif etf_reason:
            caveats.append(etf_reason + ".")
        if trends is None:
            caveats.append("Google Trends unavailable or throttled; indicator excluded.")
        derivatives, derivatives_reason = coinglass_derivatives_result(asset)
        if derivatives is None:
            caveats.append(derivatives_reason or "CoinGlass futures derivatives data unavailable.")
        else:
            # Add spot-price context so 24h liquidations are not interpreted in isolation.
            if len(candles) >= 2:
                previous_close = float(candles.close.iloc[-2])
                derivatives["price_change_24h_pct"] = (
                    (price / previous_close - 1) * 100 if previous_close else None
                )
            else:
                derivatives["price_change_24h_pct"] = None

            if len(candles) >= 31:
                close_30d_ago = float(candles.close.iloc[-31])
                derivatives["price_change_30d_pct"] = (
                    (price / close_30d_ago - 1) * 100 if close_30d_ago else None
                )
            else:
                derivatives["price_change_30d_pct"] = None
        result=score_features(Features(trends,vol,flows,cvd,ps))
        mode="live_partial"
    except Exception as e:
        price=None
        result=score_features(Features())
        trends=vol=flows=cvd=ps=None
        flow_label="Spot taker flow"
        flow_detail="Spot directional flow unavailable."
        derivatives=None
        caveats.append(f"Provider error: {type(e).__name__}.")
        mode="unavailable"

    maxima={"trends":10,"volume":20,"etf":20,"cvd":20,"price":30}
    labels={"trends":"Google Trends","volume":"Spot volume","etf":"ETF net flows","cvd":flow_label,"price":"Price structure"}
    vals={"trends":trends,"volume":vol,"etf":flows,"cvd":cvd,"price":ps}
    details={
      "trends":"Weekly interest recovering from a low base; normalized 0–100 series.",
      "volume":"Looks for capitulation sell-volume followed by expanding up-day spot volume.",
      "etf":"Daily spot crypto ETF net flows aggregated across funds. Incomplete reporting days are excluded rather than treated as zero.",
      "cvd":flow_detail,
      "price":"Confirmed daily swing higher-low and higher-high structure."
    }
    indicators=[]
    for k,v in vals.items():
        indicators.append(Indicator(key=k,label=labels[k],score=round(v*maxima[k],1) if v is not None else None,
          maximum=maxima[k],status="available" if v is not None else "missing",detail=details[k]))
    return AssetSnapshot(asset=asset,symbol=pair,price_usd=price,score=result["score"],label=result["label"],
      confirmed_bottom=result["confirmed_bottom"],data_mode=mode,as_of=datetime.now(timezone.utc).isoformat(),
      indicators=indicators,caveats=caveats,derivatives=derivatives if mode != "unavailable" else None)

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/api/v1/assets",response_model=list[AssetSnapshot])
def assets():
    return [build_snapshot(a) for a in ASSETS]

@app.get("/api/v1/assets/{asset}",response_model=AssetSnapshot)
def asset(asset:str):
    a=asset.upper()
    if a not in ASSETS:
        raise HTTPException(404,"Supported assets: BTC, ETH, SOL")
    return build_snapshot(a)


@app.post("/api/v1/history/backfill")
def historical_backfill(payload:dict):
    """Reconstruct and persist up to 730 days of BTC-only historical scores."""
    try:
        days=int(payload.get("days",730))
        return backfill_btc_history(days=days)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400,str(exc))
    except Exception as exc:
        raise HTTPException(502,f"Historical backfill failed: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/v1/history")
def historical_scores(
    asset:str="BTC",
    days:int=Query(default=730,ge=1,le=730),
    min_score:float|None=None,
    min_coverage:float=Query(default=80,ge=0,le=100),
    confirmed_only:bool=False,
):
    """Retrieve stored historical scores; defaults to the last 730 days of BTC."""
    a=asset.upper()
    if a!="BTC":
        raise HTTPException(400,"Historical backfill currently supports BTC only")
    from datetime import timedelta
    start=(datetime.now(timezone.utc).date()-timedelta(days=days)).isoformat()
    records=history_rows(a,start_date=start)
    filtered=[]
    for item in records:
        details=item.get("details") or {}
        coverage=float(details.get("coverage_pct",details.get("available_weight",0)) or 0)
        if min_score is not None and (item.get("score") is None or item["score"]<min_score):
            continue
        if coverage<min_coverage:
            continue
        if confirmed_only and not item.get("confirmed_bottom"):
            continue
        filtered.append(item)
    return {
        "asset":a,
        "days":days,
        "start_date":start,
        "records":len(filtered),
        "scores_over_70":sum(1 for item in filtered if item.get("score") is not None and item["score"]>70),
        "confirmed_bottom_days":sum(1 for item in filtered if item.get("confirmed_bottom")),
        "history":filtered,
        "note":"Only previously backfilled/imported records are returned. Scores are historical reconstructions, not live readings."
    }

@app.post("/api/v1/validation/run")
def validation(payload:dict):
    a=str(payload.get("asset","BTC")).upper()
    if a not in ASSETS:
        raise HTTPException(400,"Supported assets: BTC, ETH, SOL")
    return run_validation(a)

@app.post("/api/v1/validation/import")
def import_history(payload:dict):
    """Import pre-aligned, point-in-time daily feature rows for reproducible backtests."""
    a=str(payload.get("asset","BTC")).upper()
    if a not in ASSETS:
        raise HTTPException(400,"Supported assets: BTC, ETH, SOL")
    data=payload.get("rows",[])
    if not data:
        raise HTTPException(400,"rows is required")
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


@app.get("/api/v1/backtest/btc")
def historical_btc_backtest(
    days:int=Query(default=730,ge=1,le=730),
    min_score:float=70.0,
    min_coverage:float=Query(default=80,ge=0,le=100),
    investment_usd:float=Query(default=1000,gt=0,le=1000000),
):
    """Evaluate BTC historical score signals against subsequent daily price action."""
    try:
        return run_btc_backtest(
            days=days,
            min_score=min_score,
            min_coverage=min_coverage,
            investment_usd=investment_usd,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400,str(exc))
    except Exception as exc:
        raise HTTPException(502,f"Historical BTC backtest failed: {type(exc).__name__}: {str(exc)[:180]}")
