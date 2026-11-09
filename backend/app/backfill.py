from datetime import datetime, timedelta, timezone

import pandas as pd

from .indicators import trends_score, volume_score, etf_score, cvd_score, price_structure_score
from .providers import (
    binance_daily,
    google_trends_weekly_dated,
    etf_flow_records_result,
)
from .scoring import Features, score_features
from .store import save_row


def backfill_btc_history(days=365):
    """Build point-in-time BTC daily scores from available historical provider data.

    Binance candles supply price, volume and a taker-flow proxy. Google Trends and
    ETF observations are aligned by their publication dates. Missing inputs remain
    None; they are never backfilled with today's value or treated as zero.
    """
    if not isinstance(days, int) or days < 1 or days > 365:
        raise ValueError("days must be an integer between 1 and 365")

    # Fetch extra candles for rolling indicator warm-up before the requested window.
    candles = binance_daily("BTCUSDT", limit=min(1000, days + 100))
    if candles is None or candles.empty:
        raise RuntimeError("Binance returned no historical BTC candles")

    candles = candles.copy()
    candles["date"] = pd.to_datetime(candles["time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    # Do not score today's still-open UTC candle.
    utc_today = datetime.now(timezone.utc).date().isoformat()
    candles = candles[candles["date"] < utc_today].reset_index(drop=True)
    if candles.empty:
        raise RuntimeError("No completed daily BTC candles were returned")

    start_date = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    trends = google_trends_weekly_dated("Bitcoin") or []
    trend_records = sorted(
        (item for item in trends if item.get("date") and item.get("value") is not None),
        key=lambda item: item["date"]
    )
    etf_records, etf_reason = etf_flow_records_result("BTC")
    etf_records = etf_records or []

    trend_values = []
    etf_values = []
    saved = []
    scores_above_70 = []
    missing_sources = set()
    daily_taker_delta = (
        2 * candles["taker_buy_quote"].astype(float)
        - candles["quote_volume"].astype(float)
    )
    cumulative_taker_delta = daily_taker_delta.cumsum()

    trend_index = 0
    etf_index = 0

    for i, row in candles.iterrows():
        day = row["date"]
        while trend_index < len(trend_records) and trend_records[trend_index]["date"] <= day:
            trend_values.append(float(trend_records[trend_index]["value"]))
            trend_index += 1
        while etf_index < len(etf_records) and etf_records[etf_index]["date"] <= day:
            etf_values.append(float(etf_records[etf_index]["net_flow_usd"]))
            etf_index += 1

        # Prefix-only calculations prevent later candles from influencing this date.
        prefix = candles.iloc[: i + 1]
        trend_value = trends_score(trend_values) if len(trend_values) >= 12 else None
        volume_value = volume_score(prefix)
        etf_value = etf_score(etf_values) if len(etf_values) >= 10 else None
        cvd_value = cvd_score(cumulative_taker_delta.iloc[: i + 1].tolist())
        price_value = price_structure_score(prefix)

        features = Features(
            trends_recovery=trend_value,
            capitulation_then_demand=volume_value,
            etf_inflow_consistency=etf_value,
            spot_cvd_strength=cvd_value,
            price_structure=price_value,
        )
        result = score_features(features)
        if result["score"] is None:
            continue

        feature_values = {
            "trends": trend_value,
            "volume": volume_value,
            "etf": etf_value,
            "cvd": cvd_value,
            "price_structure": price_value,
        }
        coverage = float(result["available_weight"])
        # The threshold is deliberately explicit: partial scores below 80% coverage
        # are stored for inspection but not counted as reliable >70 candidates.
        eligible = coverage >= 80.0
        record = {
            "date": day,
            "close": float(row["close"]),
            "score": result["score"],
            "label": result["label"],
            "confirmed_bottom": result["confirmed_bottom"],
            "available_weight": coverage,
            "coverage_pct": coverage,
            "score_eligible": eligible,
            "features": feature_values,
            "data_sources": {
                "price_volume": "Binance completed daily candles",
                "cvd": "Binance spot taker-buy/sell volume proxy; not aggregated exchange CVD",
                "trends": "Dated weekly Google Trends observations",
                "etf": "Dated complete daily BTC ETF fund flows" if etf_value is not None else None,
            },
        }
        save_row("BTC", day, float(row["close"]), result, record)

        if day >= start_date:
            saved.append(record)
            if result["score"] > 70 and eligible:
                scores_above_70.append(record)

    return {
        "asset": "BTC",
        "requested_days": days,
        "start_date": start_date,
        "end_date": candles.iloc[-1]["date"],
        "stored_days": len(saved),
        "scores_over_70_with_at_least_70pct_coverage": scores_above_70,
        "coverage_summary": {
            "google_trends_weekly_observations": len(trend_records),
            "complete_etf_flow_days": len(etf_records),
            "etf_provider_note": etf_reason,
            "cvd_note": "Historical Binance taker-flow proxy used; this is not true multi-exchange spot CVD.",
            "score_note": "Scores are point-in-time reconstructions from available historical inputs. Rows with less than 80% of the configured indicator weight are stored but excluded from the >70 candidate list.",
        },
    }
