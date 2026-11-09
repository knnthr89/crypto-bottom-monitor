from datetime import datetime, timedelta, timezone

import pandas as pd

from app import backtest


def _candles_for_dates(dates):
    closes = [100.0 + i for i in range(len(dates))]
    return pd.DataFrame({
        "time": [
            int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
            for day in dates
        ],
        "close": closes,
        "low": [value * 0.99 for value in closes],
    })


def test_btc_backtest_separates_partial_and_full_coverage(monkeypatch):
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=39 - i)).isoformat() for i in range(39)]
    candles = _candles_for_dates(dates)
    signals = [
        {
            "date": dates[18],
            "score": 72.0,
            "details": {"coverage_pct": 80.0},
        },
        {
            "date": dates[19],
            "score": 73.0,
            "details": {"coverage_pct": 100.0},
        },
    ]
    monkeypatch.setattr(backtest, "history_rows", lambda *args, **kwargs: signals)
    monkeypatch.setattr(backtest, "binance_daily", lambda *args, **kwargs: candles)

    result = backtest.run_btc_backtest(days=30)

    assert result["signals_found"] == 2
    assert result["horizon_summaries"]["7d"]["partial_coverage_80_to_99_pct"]["episodes"] == 1
    assert result["horizon_summaries"]["7d"]["full_coverage_100_pct"]["episodes"] == 1
    assert result["horizon_summaries"]["7d"]["all_eligible_signals"]["episodes"] == 2
    assert "7d" in result["signals"][0]["horizons"]
    assert result["signals"][0]["horizons"]["7d"]["max_drawdown_pct"] < 0

    # Two adjacent qualifying days are one episode, not two independent entries.
    threshold = result["threshold_and_episode_analysis"]["70"]
    assert threshold["episodes_found"] == 1
    assert threshold["signal_days"] == 2
    assert threshold["episodes"][0]["signal_days"] == 2


def test_episode_analysis_compares_lump_sum_and_staged_buying(monkeypatch):
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=99 - i)).isoformat() for i in range(99)]
    candles = _candles_for_dates(dates)
    signals = [{
        "date": dates[10],
        "score": 76.0,
        "details": {"coverage_pct": 100.0},
    }]
    monkeypatch.setattr(backtest, "history_rows", lambda *args, **kwargs: signals)
    monkeypatch.setattr(backtest, "binance_daily", lambda *args, **kwargs: candles)

    result = backtest.run_btc_backtest(days=90)
    episode = result["threshold_and_episode_analysis"]["75"]["episodes"][0]
    thirty_day = episode["horizons"]["30d"]

    assert "signal_entry" in thirty_day
    assert "weekly_dca" in thirty_day
    assert "monthly_dca" in thirty_day
    assert thirty_day["weekly_dca"]["average_entry_price_usd"] >= 0
    assert result["methodology"]["episode_grouping"].startswith("Consecutive")


def test_btc_backtest_rejects_days_over_365():
    try:
        backtest.run_btc_backtest(days=366)
    except ValueError as exc:
        assert "between 1 and 365" in str(exc)
    else:
        raise AssertionError("Expected invalid days to raise ValueError")
