from datetime import datetime, timedelta, timezone

import pandas as pd

from .providers import binance_daily
from .store import history_rows


HORIZONS = (7, 30, 60, 90)
THRESHOLDS = (60, 65, 70, 75, 80)


def _summarize(rows, count_label="signals"):
    if not rows:
        return {
            count_label: 0,
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
        count_label: len(rows),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 1),
        "average_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(float(pd.Series(returns).median()), 2),
        "best_return_pct": round(max(returns), 2),
        "worst_return_pct": round(min(returns), 2),
        "average_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 2),
    }


def _coverage(row):
    details = row.get("details") or {}
    return float(details.get("coverage_pct", details.get("available_weight", 0)) or 0)


def _group_episodes(records, candle_by_date):
    """Group consecutive qualifying signal dates; use the first day as the entry."""
    usable = []
    for row in records:
        signal_date = str(row["date"])[:10]
        if signal_date in candle_by_date:
            usable.append({
                "date": signal_date,
                "score": float(row["score"]),
                "coverage_pct": _coverage(row),
                "entry_index": candle_by_date[signal_date],
            })
    usable.sort(key=lambda item: item["date"])

    episodes = []
    for signal in usable:
        signal_day = datetime.strptime(signal["date"], "%Y-%m-%d").date()
        if not episodes:
            episodes.append({"signals": [signal]})
            continue
        previous_day = datetime.strptime(episodes[-1]["signals"][-1]["date"], "%Y-%m-%d").date()
        if (signal_day - previous_day).days == 1:
            episodes[-1]["signals"].append(signal)
        else:
            episodes.append({"signals": [signal]})

    output = []
    for number, episode in enumerate(episodes, start=1):
        first = episode["signals"][0]
        output.append({
            "episode": number,
            "start_date": first["date"],
            "end_date": episode["signals"][-1]["date"],
            "signal_days": len(episode["signals"]),
            "entry_index": first["entry_index"],
            "entry_score": first["score"],
            "coverage_pct": first["coverage_pct"],
        })
    return output


def _holding_outcome(candles, entry_index, horizon, purchase_interval=None):
    end_index = entry_index + horizon
    if end_index >= len(candles):
        return None
    future = candles.iloc[entry_index + 1:end_index + 1]
    if len(future) != horizon:
        return None

    exit_price = float(candles.iloc[end_index]["close"])
    if purchase_interval is None:
        average_entry = float(candles.iloc[entry_index]["close"])
        purchase_days = [0]
    else:
        # Invest equal amounts at day 0 and each interval before the exit date.
        purchase_days = list(range(0, horizon, purchase_interval))
        purchase_prices = [
            float(candles.iloc[entry_index + day]["close"])
            for day in purchase_days
        ]
        # Equal-dollar purchases buy different BTC quantities at different prices.
        # The effective cost per BTC is therefore the harmonic mean.
        if any(price <= 0 for price in purchase_prices):
            return None
        average_entry = len(purchase_prices) / sum(1.0 / price for price in purchase_prices)

    if average_entry <= 0:
        return None
    return {
        "return_pct": (exit_price / average_entry - 1) * 100,
        "max_drawdown_pct": (float(future["low"].min()) / average_entry - 1) * 100,
        "exit_date": str(candles.iloc[end_index]["date"]),
        "exit_price_usd": round(exit_price, 2),
        "average_entry_price_usd": round(average_entry, 2),
        "purchase_days_after_signal": purchase_days,
    }


def _calendar_dca_benchmark(candles):
    """Evaluate fixed-calendar weekly/monthly DCA, independent of score signals.

    Start windows are sampled every 7 or 30 completed candles from the first
    available candle. Windows overlap, so observations are not independent.
    """
    result = {}
    for horizon in HORIZONS:
        strategies = {"weekly_dca": [], "monthly_dca": []}
        for interval, name in ((7, "weekly_dca"), (30, "monthly_dca")):
            for entry_index in range(0, max(0, len(candles) - horizon), interval):
                outcome = _holding_outcome(candles, entry_index, horizon, interval)
                if outcome is not None:
                    strategies[name].append(outcome)
        result[f"{horizon}d"] = {
            name: _summarize(rows, count_label="calendar_windows")
            for name, rows in strategies.items()
        }
    return result


def _build_episode_analysis(records, candles, candle_by_date, min_coverage):
    analysis = {}
    for threshold in THRESHOLDS:
        qualifying = [
            row for row in records
            if row.get("score") is not None
            and float(row["score"]) > threshold
            and _coverage(row) >= min_coverage
        ]
        episodes = _group_episodes(qualifying, candle_by_date)
        horizon_rows = {horizon: {"signal_entry": [], "weekly_dca": [], "monthly_dca": []}
                        for horizon in HORIZONS}
        episode_details = []

        for episode in episodes:
            detail = {key: value for key, value in episode.items() if key != "entry_index"}
            detail["entry_price_usd"] = round(float(candles.iloc[episode["entry_index"]]["close"]), 2)
            detail["horizons"] = {}
            for horizon in HORIZONS:
                outcomes = {
                    "signal_entry": _holding_outcome(candles, episode["entry_index"], horizon),
                    "weekly_dca": _holding_outcome(candles, episode["entry_index"], horizon, 7),
                    "monthly_dca": _holding_outcome(candles, episode["entry_index"], horizon, 30),
                }
                if outcomes["signal_entry"] is None:
                    continue
                detail["horizons"][f"{horizon}d"] = {}
                for strategy, outcome in outcomes.items():
                    if outcome is None:
                        continue
                    horizon_rows[horizon][strategy].append(outcome)
                    detail["horizons"][f"{horizon}d"][strategy] = {
                        key: value for key, value in outcome.items()
                        if key != "purchase_days_after_signal"
                    }
            episode_details.append(detail)

        analysis[str(threshold)] = {
            "score_rule": f"score > {threshold}",
            "episodes_found": len(episodes),
            "signal_days": sum(item["signal_days"] for item in episodes),
            "horizon_summaries": {
                f"{horizon}d": {
                    strategy: _summarize(rows, count_label="episodes")
                    for strategy, rows in horizon_rows[horizon].items()
                }
                for horizon in HORIZONS
            },
            "episodes": episode_details,
        }
    return analysis


def run_btc_backtest(days=365, min_score=70.0, min_coverage=80.0):
    """Evaluate BTC score signals, grouped episodes, and staged-buy benchmarks."""
    if not isinstance(days, int) or days < 1 or days > 365:
        raise ValueError("days must be an integer between 1 and 365")
    if not 0 <= float(min_coverage) <= 100:
        raise ValueError("min_coverage must be between 0 and 100")

    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=days)).isoformat()
    records = history_rows("BTC", start_date=start_date)

    # Extra candles provide forward outcomes for signals near the start of the window.
    candles = binance_daily("BTCUSDT", limit=min(1000, days + 100))
    if candles is None or candles.empty:
        raise RuntimeError("Binance returned no daily candles for backtest")

    candles = candles.copy()
    candles["date"] = pd.to_datetime(candles["time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    candles = candles[candles["date"] < today.isoformat()].sort_values("date").reset_index(drop=True)
    candle_by_date = {row["date"]: index for index, row in candles.iterrows()}

    eligible = [
        row for row in records
        if row.get("score") is not None
        and float(row["score"]) > float(min_score)
        and _coverage(row) >= float(min_coverage)
    ]
    evaluated = {h: {"partial": [], "full": []} for h in HORIZONS}
    signal_rows = []

    for signal in eligible:
        signal_date = str(signal["date"])[:10]
        entry_index = candle_by_date.get(signal_date)
        if entry_index is None:
            continue
        entry_price = float(candles.iloc[entry_index]["close"])
        if entry_price <= 0:
            continue
        coverage = _coverage(signal)
        group = "full" if coverage >= 99.999 else "partial"
        item = {
            "date": signal_date,
            "score": float(signal["score"]),
            "coverage_pct": round(coverage, 1),
            "entry_price_usd": round(entry_price, 2),
            "horizons": {},
        }

        for horizon in HORIZONS:
            outcome = _holding_outcome(candles, entry_index, horizon)
            if outcome is None:
                continue
            item["horizons"][f"{horizon}d"] = {
                "return_pct": round(outcome["return_pct"], 2),
                "max_drawdown_pct": round(outcome["max_drawdown_pct"], 2),
                "exit_date": outcome["exit_date"],
                "exit_price_usd": outcome["exit_price_usd"],
            }
            evaluated[horizon][group].append(outcome)
        signal_rows.append(item)

    summaries = {}
    for horizon in HORIZONS:
        summaries[f"{horizon}d"] = {
            "partial_coverage_80_to_99_pct": _summarize(evaluated[horizon]["partial"]),
            "full_coverage_100_pct": _summarize(evaluated[horizon]["full"]),
            "all_eligible_signals": _summarize(
                evaluated[horizon]["partial"] + evaluated[horizon]["full"]
            ),
        }

    episode_analysis = _build_episode_analysis(
        records, candles, candle_by_date, float(min_coverage)
    )
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
        "threshold_and_episode_analysis": episode_analysis,
        "calendar_dca_benchmark": _calendar_dca_benchmark(candles),
        "methodology": {
            "entry": "Signal-date completed daily candle close; episode analysis enters on the first qualifying day of each consecutive signal cluster.",
            "episode_grouping": "Consecutive calendar days with qualifying scores are grouped as one episode.",
            "weekly_dca": "Equal purchases at the episode start and every 7 days after, up to but not including the exit day.",
            "monthly_dca": "Equal purchases at the episode start and every 30 days after, up to but not including the exit day.",
            "dca_comparison": "Equal-dollar installments are evaluated using the harmonic mean purchase price (total BTC acquired is the sum of each installment divided by its price). Episode DCA begins on the first signal day; calendar DCA is a separate fixed schedule independent of score signals.",
            "calendar_dca_benchmark": "Weekly and monthly calendar-DCA windows begin every 7 or 30 completed candles, respectively, from the first available candle, regardless of score. Windows overlap and are not independent; compare these broad baseline results cautiously with the smaller signal-episode samples.",
            "exit": "Close exactly 7, 30, 60 or 90 completed daily candles after entry.",
            "max_drawdown": "Lowest daily candle low during the forward holding window, measured against the strategy's average entry price.",
            "thresholds": "Episode analysis is calculated separately for score thresholds greater than 60, 65, 70, 75 and 80, using the requested minimum coverage.",
            "limitations": [
                "Historical scores are reconstructed from available data and may not represent what was known in real time.",
                "The threshold and episode summaries count episodes, not consecutive signal days; the small number of episodes still limits statistical confidence.",
                "Weekly and monthly DCA start on each episode's first signal date, so this tests lump-sum versus staged buying after the same signal, not DCA versus a market-wide calendar schedule.",
                "Returns exclude fees, spreads, slippage and taxes.",
                "A positive historical return does not establish predictive ability or guarantee future results."
            ],
        },
    }
