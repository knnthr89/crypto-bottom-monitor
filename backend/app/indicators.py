import numpy as np
import pandas as pd

def trends_score(series):
    """Series of weekly Google Trends 0..100 values."""
    if series is None or len(series) < 12: return None
    s = pd.Series(series, dtype=float).dropna()
    if len(s) < 12: return None
    recent = s.tail(4).mean()
    prior = s.iloc[-12:-4].mean()
    low = s.iloc[-12:].min()
    if prior <= 0: return 0.5
    recovery = (recent-prior)/max(prior,1)
    from_low = (recent-low)/max(prior,1)
    return float(np.clip(0.5 + recovery*1.5 + from_low*.5, 0, 1))

def volume_score(df):
    """Daily OHLCV columns: close, quote_volume. Detect high-volume selloff then expanding up-day volume."""
    if df is None or len(df) < 35: return None
    d=df.copy()
    d["ret"]=d.close.pct_change()
    baseline=d.quote_volume.rolling(30).median()
    d["relvol"]=d.quote_volume/baseline
    recent=d.tail(14)
    capitulation=((recent.ret < -0.03) & (recent.relvol > 1.8)).any()
    buying=((recent.ret > 0.01) & (recent.relvol > 1.25)).sum()
    return float(np.clip((0.45 if capitulation else 0) + min(buying/4,1)*0.55,0,1))

def etf_score(flows):
    """Daily USD net flow values, oldest to newest. Missing feed must be None, not zero."""
    if flows is None or len(flows)<10: return None
    s=pd.Series(flows,dtype=float).tail(20)
    positive=(s>0).mean()
    net=s.sum()
    scale=np.tanh(net/100_000_000)
    return float(np.clip(0.65*positive+0.35*(scale+1)/2,0,1))

def cvd_score(cvd):
    """Spot cumulative-volume-delta series, consistent exchange universe."""
    if cvd is None or len(cvd)<14: return None
    s=pd.Series(cvd,dtype=float).tail(14)
    delta=s.iloc[-1]-s.iloc[0]
    scale=delta/(abs(s.iloc[0])+abs(delta)+1e-9)
    positive_days=(s.diff()>0).mean()
    return float(np.clip(.5 + .35*scale + .3*(positive_days-.5),0,1))

def price_structure_score(df, left=3, right=3):
    """Confirmed daily swing structure. Right-side candles must have closed before pivot is actionable."""
    if df is None or len(df)<60: return None
    lows=df.low.to_numpy(dtype=float); highs=df.high.to_numpy(dtype=float)
    piv_l=[]; piv_h=[]
    for i in range(left, len(df)-right):
        if lows[i] == min(lows[i-left:i+right+1]): piv_l.append((i,float(lows[i])))
        if highs[i] == max(highs[i-left:i+right+1]): piv_h.append((i,float(highs[i])))
    if len(piv_l)<2 or len(piv_h)<2: return 0.0
    l1,l2=piv_l[-2],piv_l[-1]; h1,h2=piv_h[-2],piv_h[-1]
    hl=l2[1] > l1[1]
    hh=h2[1] > h1[1]
    if hl and hh: return 1.0
    if hl: return 2/3
    if len(piv_l)>=1 and len(piv_h)>=1: return 1/3
    return 0.0
