from datetime import datetime, timedelta, timezone

import pandas as pd

from .providers import binance_daily
from .store import history_rows


def _summarize(rows):
    if not rows:
        return {
            "signals": 0,
            "win_rate_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
            "average_max_drawdown_pct": None,
        }
    returns = [item["return_pct"] for item in rows]
    drawdowns = [item["max_drawdown_pct"] for item in rows]
    return {
        "signals": len(rows),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 1),
        "average_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(float(pd.Series(returns).median()), 2),
        "best_return_pct": round(max(returns), 2),
        "worst_return_pct": round(min(returns), 2),
        "average_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 2),
    }


def run_btc_backtest(days=365, min_score=70.0, min_coverage=80.0):
    """Evaluate historical BTC score signals against subsequent completed Binance candles."""
    if not isinstance(days, int) or days < 1 or days > 365:
        raise ValueError("days must be an integer between 1 and 365")
    if not 0 <= float(min_coverage) <= 100:
        raise ValueError("min_coverage must be between 0 and 100")

    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=days)).isoformat()
    records = history_rows("BTC", start_date=start_date)
    records = [
        row for row in records
        if row.get("score") is not None
        and float(row["score"]) > float(min_score)
        and float((row.get("details") or {}).get("coverage_pct",
                    (row.get("details") or {}).get("available_weight", 0)) or 0) >= float(min_coverage)
    ]

    # Extra candles provide forward outcomes for signals near the start of the window.
    candles = binance_daily("BTCUSDT", limit=min(1000, days + 100))
    if candles is None or candles.empty:
        raise RuntimeError("Binance returned no daily candles for backtest")

    candles = candles.copy()
    candles["date"] = pd.to_datetime(candles["time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    candles = candles[candles["date"] < today.isoformat()].sort_values("date").reset_index(drop=True)
    candle_by_date = {row["date"]: index for index, row in candles.iterrows()}
    horizons = (7, 30, 60, 90)
    evaluated = {h: {"partial": [], "full": []} for h in horizons}
    signal_rows = []

    for signal in records:
        signal_date = str(signal["date"])[:10]
        entry_index = candle_by_date.get(signal_date)
        if entry_index is None:
            continue
        entry_price = float(candles.iloc[entry_index]["close"])
        if entry_price <= 0:
            continue
        details = signal.get("details") or {}
        coverage = float(details.get("coverage_pct", details.get("available_weight", 0)) or 0)
        group = "full" if coverage >= 99.999 else "partial"
        item = {
            "date": signal_date,
            "score": float(signal["score"]),
            "coverage_pct": round(coverage, 1),
            "entry_price_usd": round(entry_price, 2),
            "horizons": {},
        }

        for horizon in horizons:
            end_index = entry_index + horizon
            if end_index >= len(candles):
                continue
            future = candles.iloc[entry_index + 1:end_index + 1]
            if len(future) != horizon:
                continue
            exit_price = float(candles.iloc[end_index]["close"])
            future_low = float(future["low"].min())
            return_pct = (exit_price / entry_price - 1) * 100
            drawdown_pct = (future_low / entry_price - 1) * 100
            outcome = {
                "return_pct": round(return_pct, 2),
                "max_drawdown_pct": round(drawdown_pct, 2),
                "exit_date": str(candles.iloc[end_index]["date"]),
                "exit_price_usd": round(exit_price, 2),
            }
            item["horizons"][f"{horizon}d"] = outcome
            evaluated[horizon][group].append({
                "return_pct": return_pct,
                "max_drawdown_pct": drawdown_pct,
            })
        signal_rows.append(item)

    summaries = {}
    for horizon in horizons:
        summaries[f"{horizon}d"] = {
            "partial_coverage_80_to_99_pct": _summarize(evaluated[horizon]["partial"]),
            "full_coverage_100_pct": _summarize(evaluated[horizon]["full"]),
            "all_eligible_signals": _summarize(
                evaluated[horizon]["partial"] + evaluated[horizon]["full"]
            ),
        }

    return {
        "asset": "BTC",
        "start_date": start_date,
        "end_date": candles.iloc[-1]["date"],
        "signal_rule": f"Historical score > {float(min_score)} and coverage >= {float(min_coverage)}%",
        "signals_found": len(signal_rows),
        "signals_with_any_complete_forward_horizon": sum(
            1 for item in signal_rows if item["horizons"]
        ),
        "horizon_summaries": summaries,
        "signals": signal_rows,
        "methodology": {
            "entry": "Signal-date completed daily candle close",
            "exit": "Close exactly 7, 30, 60 or 90 completed daily candles after entry",
            "max_drawdown": "Lowest daily candle low during the forward holding window, measured against entry close",
            "partial_vs_full": "Partial means 80% to less than 100% configured indicator-weight coverage; full means 100%",
            "limitations": [
                "Historical scores are reconstructed from available data and may not represent what was known in real time.",
                "Overlapping signal dates are counted separately; results are not independent trades.",
                "Returns exclude fees, spreads, slippage and taxes.",
                "A positive historical return does not establish predictive ability or guarantee future results."
            ],
        },
    }
