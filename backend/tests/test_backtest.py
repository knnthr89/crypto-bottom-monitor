from datetime import datetime, timedelta, timezone

import pandas as pd

from app import backtest


def test_btc_backtest_separates_partial_and_full_coverage(monkeypatch):
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=39 - i)).isoformat() for i in range(39)]
    closes = [100.0 + i for i in range(39)]
    candles = pd.DataFrame({
        "time": [
            int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
            for day in dates
        ],
        "close": closes,
        "low": [value * 0.99 for value in closes],
    })
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
    assert result["horizon_summaries"]["7d"]["partial_coverage_80_to_99_pct"]["signals"] == 1
    assert result["horizon_summaries"]["7d"]["full_coverage_100_pct"]["signals"] == 1
    assert result["horizon_summaries"]["7d"]["all_eligible_signals"]["signals"] == 2
    assert "7d" in result["signals"][0]["horizons"]
    assert result["signals"][0]["horizons"]["7d"]["max_drawdown_pct"] < 0


def test_btc_backtest_rejects_days_over_365():
    try:
        backtest.run_btc_backtest(days=366)
    except ValueError as exc:
        assert "between 1 and 365" in str(exc)
    else:
        raise AssertionError("Expected invalid days to raise ValueError")
