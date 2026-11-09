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
    assert result["horizon_summaries"]["7d"]["partial_coverage_80_to_99_pct"]["signals"] == 1
    assert result["horizon_summaries"]["7d"]["full_coverage_100_pct"]["signals"] == 1
    assert result["horizon_summaries"]["7d"]["all_eligible_signals"]["signals"] == 2
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
    assert "harmonic mean" in result["methodology"]["dca_comparison"]
    assert "calendar_windows" in result["calendar_dca_benchmark"]["30d"]["weekly_dca"]

    matched = result["matched_investment_analysis"]["75"]
    assert matched["investment_budget_usd_per_episode"] == 1000.0
    matched_episode = matched["episodes"][0]
    signal_entry = matched_episode["horizons"]["30d"]["signal_entry"]
    weekly_dca = matched_episode["horizons"]["30d"]["weekly_dca"]
    assert signal_entry["budget_usd"] == weekly_dca["budget_usd"] == 1000.0
    assert signal_entry["exit_date"] == weekly_dca["exit_date"]
    assert signal_entry["btc_acquired"] > 0
    assert "final_value_usd" in weekly_dca


def test_btc_backtest_rejects_days_over_730():
    try:
        backtest.run_btc_backtest(days=731)
    except ValueError as exc:
        assert "between 1 and 730" in str(exc)
    else:
        raise AssertionError("Expected invalid days to raise ValueError")



def test_equal_dollar_dca_uses_harmonic_mean_purchase_cost():
    candles = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "close": [100.0, 200.0, 150.0, 180.0],
        "low": [99.0, 198.0, 148.0, 178.0],
    })

    outcome = backtest._holding_outcome(candles, 0, 3, 1)
    expected_cost = 3 / (1 / 100.0 + 1 / 200.0 + 1 / 150.0)

    assert outcome["average_entry_price_usd"] == round(expected_cost, 2)



def test_equal_dollar_investment_tracks_btc_and_final_value():
    candles = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "close": [100.0, 200.0, 150.0, 180.0],
        "low": [99.0, 198.0, 148.0, 178.0],
    })

    outcome = backtest._equal_dollar_investment(
        candles, entry_index=0, horizon=3, budget_usd=900, interval_days=1
    )

    # Three $300 purchases acquire 3 + 1.5 + 2 BTC.
    assert outcome["installments"] == 3
    assert outcome["btc_acquired"] == 6.5
    assert outcome["average_entry_price_usd"] == round(900 / 6.5, 2)
    assert outcome["final_value_usd"] == 1170.0
    assert outcome["profit_loss_usd"] == 270.0
    assert outcome["return_pct"] == 30.0


def test_matched_strategies_use_same_start_and_budget():
    candles = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
                 "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
        "close": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0],
        "low": [99.0, 109.0, 119.0, 129.0, 139.0, 149.0, 159.0, 169.0],
    })

    lump_sum = backtest._equal_dollar_investment(candles, 0, 7, 1000)
    weekly = backtest._equal_dollar_investment(candles, 0, 7, 1000, 7)

    assert lump_sum["budget_usd"] == weekly["budget_usd"]
    assert lump_sum["exit_date"] == weekly["exit_date"]
    assert lump_sum["exit_price_usd"] == weekly["exit_price_usd"]
    assert lump_sum["purchase_days_after_signal"] == [0]
    assert weekly["purchase_days_after_signal"] == [0]



def test_full_period_benchmark_compares_equal_budget_and_tracks_portfolio_drawdown():
    from app.benchmarks import full_period_benchmark

    candles = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04",
                 "2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"],
        "close": [100.0, 90.0, 80.0, 85.0, 95.0, 105.0, 110.0, 120.0],
    })
    result = full_period_benchmark(candles, "2024-01-01", 1000.0)

    assert result["available"] is True
    strategies = result["strategies"]
    assert strategies["buy_and_hold"]["budget_usd"] == 1000.0
    assert strategies["weekly_dca"]["budget_usd"] == 1000.0
    assert strategies["monthly_dca"]["budget_usd"] == 1000.0
    assert strategies["buy_and_hold"]["purchase_count"] == 1
    assert strategies["weekly_dca"]["purchase_count"] == 2
    assert strategies["monthly_dca"]["purchase_count"] == 1
    assert "max_portfolio_drawdown_pct" in strategies["weekly_dca"]



def test_entry_timing_comparison_compares_signal_and_delayed_entries(monkeypatch):
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=499 - i)).isoformat() for i in range(499)]
    candles = _candles_for_dates(dates)
    signals = [{
        "date": dates[10],
        "score": 78.0,
        "details": {"coverage_pct": 100.0},
    }]
    monkeypatch.setattr(backtest, "history_rows", lambda *args, **kwargs: signals)
    monkeypatch.setattr(backtest, "binance_daily", lambda *args, **kwargs: candles)

    result = backtest.run_btc_backtest(days=400)
    timing = result["entry_timing_comparison"]["75"]
    assert timing["signal_episodes"] == 1
    assert timing["signal_days"] == 1
    summary = timing["horizon_summaries"]["30d"]
    assert summary["signal_day"]["observations"] == 1
    assert summary["wait_7_days"]["observations"] == 1
    assert summary["wait_30_days"]["observations"] == 1
    assert summary["non_signal_calendar_days"]["observations"] > 1
