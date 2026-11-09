def full_period_benchmark(candles, start_date, budget_usd):
    """Compare buy-and-hold with calendar DCA over identical dates and budget."""
    window = candles[candles["date"] >= start_date].reset_index(drop=True)
    if len(window) < 2:
        return {"available": False, "reason": "Insufficient completed candles"}
    end_price = float(window.iloc[-1]["close"])
    strategies = {}
    for name, interval in (("buy_and_hold", None), ("weekly_dca", 7), ("monthly_dca", 30)):
        purchase_days = [0] if interval is None else list(range(0, len(window), interval))
        installment = float(budget_usd) / len(purchase_days)
        btc = 0.0
        cash = float(budget_usd)
        equity = []
        for index, candle in window.iterrows():
            if index in purchase_days:
                price = float(candle["close"])
                if price <= 0:
                    continue
                btc += installment / price
                cash -= installment
            equity.append(btc * float(candle["close"]) + cash)
        final_value = btc * end_price + cash
        peak = equity[0]
        drawdowns = []
        for value in equity:
            peak = max(peak, value)
            drawdowns.append((value / peak - 1) * 100 if peak else 0.0)
        invested = float(budget_usd) - cash
        strategies[name] = {
            "budget_usd": round(float(budget_usd), 2),
            "btc_acquired": round(btc, 8),
            "amount_invested_usd": round(invested, 2),
            "cash_remaining_usd": round(cash, 2),
            "average_entry_price_usd": round(invested / btc, 2) if btc else None,
            "start_date": str(window.iloc[0]["date"]),
            "end_date": str(window.iloc[-1]["date"]),
            "end_price_usd": round(end_price, 2),
            "final_value_usd": round(final_value, 2),
            "profit_loss_usd": round(final_value - float(budget_usd), 2),
            "return_pct": round((final_value / float(budget_usd) - 1) * 100, 2),
            "max_portfolio_drawdown_pct": round(min(drawdowns), 2),
            "purchase_count": len(purchase_days),
        }
    return {
        "available": True,
        "comparison_basis": "Same total budget and dates; uninvested DCA cash remains in the portfolio until scheduled purchases.",
        "investment_budget_usd": round(float(budget_usd), 2),
        "strategies": strategies,
    }
