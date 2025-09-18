import pandas as pd
import numpy as np

def compute_baseline(res_df: pd.DataFrame) -> pd.Series:
    # trailing 14d median ADR per room_type (based on history)
    baseline = res_df.groupby('room_type')['adr'].rolling(14, min_periods=3).median().groupby(level=0).transform('last')
    # Fallback to overall median per room_type if NaN
    fallback = res_df.groupby('room_type')['adr'].transform('median')
    return baseline.fillna(fallback)

def choose_price(baseline: float, proj_occ: float, comp_median: float | None) -> float:
    if np.isnan(baseline) or baseline <= 0:
        baseline = 100.0
    comp = comp_median if comp_median is not None and comp_median > 0 else baseline
    if proj_occ < 0.5:
        price = max(baseline * 0.90, comp * 0.95)
    elif proj_occ < 0.70:
        price = max(baseline * 1.00, comp * 1.00)
    elif proj_occ < 0.85:
        price = max(baseline * 1.08, comp * 1.05)
    else:
        price = max(baseline * 1.15, comp * 1.10)
    return round(float(price), 2)
