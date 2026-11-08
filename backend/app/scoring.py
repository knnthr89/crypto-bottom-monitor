from dataclasses import dataclass
from typing import Optional

WEIGHTS = {"trends":10, "volume":20, "etf":20, "cvd":20, "price":30}

@dataclass
class Features:
    trends_recovery: Optional[float] = None # 0..1
    capitulation_then_demand: Optional[float] = None # 0..1
    etf_inflow_consistency: Optional[float] = None # 0..1
    spot_cvd_strength: Optional[float] = None # 0..1
    price_structure: Optional[float] = None # 0, 1/3, 2/3, 1

def _bounded(v):
    return None if v is None else max(0.0, min(1.0, float(v)))

def score_features(f: Features):
    vals = {
        "trends": _bounded(f.trends_recovery),
        "volume": _bounded(f.capitulation_then_demand),
        "etf": _bounded(f.etf_inflow_consistency),
        "cvd": _bounded(f.spot_cvd_strength),
        "price": _bounded(f.price_structure),
    }
    available = sum(WEIGHTS[k] for k,v in vals.items() if v is not None)
    total = sum(WEIGHTS[k]*v for k,v in vals.items() if v is not None)
    score = round(total * 100 / available, 1) if available else None
    positive = sum(1 for k in ("trends","volume","etf","cvd") if vals[k] is not None and vals[k] >= .5)
    price_confirmed = vals["price"] == 1.0
    confirmed = bool(score is not None and score >= 70 and price_confirmed and positive >= 2)
    if confirmed: label = "strong_confirmation"
    elif score is None: label = "insufficient_data"
    elif score >= 50: label = "recovery_developing"
    elif score >= 25: label = "early_accumulation"
    else: label = "bearish"
    return {"score":score, "label":label, "confirmed_bottom":confirmed,
            "normalized":vals, "available_weight":available,
            "positive_supporting_indicators":positive}
