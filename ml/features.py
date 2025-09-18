import pandas as pd
from datetime import timedelta

def build_features(reservations: pd.DataFrame, competitors: pd.DataFrame | None) -> pd.DataFrame:
    df = reservations.copy()
    df['stay_date'] = pd.to_datetime(df['stay_date'])
    df['dow'] = df['stay_date'].dt.dayofweek
    # Lagged occupancy (yesterday for same room)
    df = df.sort_values(['room_type','stay_date'])
    df['lag_occ_1'] = df.groupby('room_type')['occupancy'].shift(1)
    df['roll_occ_7'] = df.groupby('room_type')['occupancy'].rolling(7, min_periods=2).mean().reset_index(0,drop=True)
    # Simple seasonality flags
    df['is_weekend'] = df['dow'].isin([4,5]).astype(int)
    # Merge competitor median for same date/room
    if competitors is not None and not competitors.empty:
        comp = competitors.groupby(['stay_date','room_type'])['rate'].median().reset_index().rename(columns={'rate':'comp_median'})
        df = df.merge(comp, on=['stay_date','room_type'], how='left')
    else:
        df['comp_median'] = None
    # Target: occupancy (as pct 0-1)
    df['target'] = df['occupancy'] / 100.0
    feat_cols = ['dow','lag_occ_1','roll_occ_7','is_weekend','comp_median']
    return df, feat_cols
