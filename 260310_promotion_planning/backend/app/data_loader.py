"""Load promotion data from agentic-analytics CSV."""

import os
from pathlib import Path

import pandas as pd

# Default: use local data; override with DATA_PATH env to point to agentic-analytics
DATA_DIR = Path(os.getenv("DATA_PATH", Path(__file__).resolve().parent.parent / "data"))
DEFAULT_CSV = DATA_DIR / "synthetic_promotions_snacks_bev.csv"

_df: pd.DataFrame | None = None


def load_promotions_df() -> pd.DataFrame:
    """Load promotions CSV into DataFrame. Cached in memory."""
    global _df
    if _df is not None:
        return _df
    if not DEFAULT_CSV.exists():
        raise FileNotFoundError(
            f"Promotion data not found at {DEFAULT_CSV}. "
            "Set DATA_PATH to agentic-analytics data directory or copy synthetic_promotions_snacks_bev.csv here."
        )
    _df = pd.read_csv(DEFAULT_CSV)
    return _df


def get_filter_options() -> dict:
    """Return unique values for filter dropdowns."""
    df = load_promotions_df()
    return {
        "markets": sorted(df["market"].dropna().unique().tolist()),
        "retailers": sorted(df["retailer"].dropna().unique().tolist()),
        "segments": sorted(df["segment"].dropna().unique().tolist()),
        "categories": sorted(df["category"].dropna().unique().tolist()),
        "brands": sorted(df["brand"].dropna().unique().tolist()),
        "offer_types": sorted(df["offer_type"].dropna().unique().tolist()),
    }


def get_stats() -> dict:
    """Return aggregate stats for dashboard."""
    df = load_promotions_df()
    return {
        "total_promotions": int(len(df)),
        "total_revenue": float(df["revenue"].sum()),
        "total_incremental_revenue": float(df["incremental_revenue"].sum()),
        "total_profit_system": float(df["profit_system"].sum()),
        "total_incremental_profit": float(df["incremental_profit_system"].sum()),
        "total_promo_investment": float(df["promo_investment"].sum()),
        "avg_uplift_pct": float(df["promo_uplift_pct"].mean()) if "promo_uplift_pct" in df.columns else None,
        "markets_count": int(df["market"].nunique()),
        "retailers_count": int(df["retailer"].nunique()),
        "brands_count": int(df["brand"].nunique()),
    }
