import numpy as np
from .store import rows

def run_validation(asset):
    data=rows(asset)
    closes=[x[1] for x in data]
    signals=[i for i,x in enumerate(data) if x[3]==1]
    result={"asset":asset,"rows":len(data),"signals":len(signals),"horizons":{}}
    for days in (30,60,90):
        rets=[]
        for i in signals:
            if i+days < len(closes) and closes[i]:
                rets.append(closes[i+days]/closes[i]-1)
        result["horizons"][str(days)] = {
          "observations":len(rets),
          "hit_rate":round(float(np.mean(np.array(rets)>0)),4) if rets else None,
          "mean_return":round(float(np.mean(rets)),4) if rets else None,
          "median_return":round(float(np.median(rets)),4) if rets else None
        }
    result["warning"]="Exploratory only. Signals must be generated using data available at each date; include fees/slippage and walk-forward tests."
    return result
