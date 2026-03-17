from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SimulationSummary:
    num_candidates_in: int
    num_candidates_scored: int
    pred_roi_min: float
    pred_roi_max: float
    pred_roi_positive_count: int

def add_time_features(
    df: pd.DataFrame,
    *,
    start_col: str = "promo_start_date",
    end_col: str = "promo_end_date",
) -> pd.DataFrame:
    d = df.copy()
    d[start_col] = pd.to_datetime(d[start_col])
    d[end_col] = pd.to_datetime(d[end_col])

    # Use promo midpoint as the "time" of the event
    midpoint = d[start_col] + (d[end_col] - d[start_col]) / 2
    d["promo_mid_date"] = midpoint.dt.floor("D")

    # Trend index (weeks since first date)
    min_date = d["promo_mid_date"].min()
    d["t_weeks"] = ((d["promo_mid_date"] - min_date).dt.days / 7.0).astype(float)

    # Seasonality
    iso = d["promo_mid_date"].dt.isocalendar()
    d["iso_week"] = iso.week.astype(int)
    d["month"] = d["promo_mid_date"].dt.month.astype(int)
    d["quarter"] = d["promo_mid_date"].dt.quarter.astype(int)
    d["year"] = d["promo_mid_date"].dt.year.astype(int)

    # A simple weekly bucket (for promo-pressure aggregation)
    d["promo_week_start"] = d["promo_mid_date"].dt.to_period("W").apply(lambda r: r.start_time)

    return d


def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    d["unit_price"] = pd.to_numeric(d["unit_price"], errors="coerce")
    d["promo_unit_price"] = pd.to_numeric(d["promo_unit_price"], errors="coerce")
    d["discount_depth"] = pd.to_numeric(d["discount_depth"], errors="coerce")

    # Recover missing unit_price from promo_unit_price and discount_depth
    mask_no_unit = (d["unit_price"].isna() | (d["unit_price"] == 0)) & (d["discount_depth"] > 0)
    d.loc[mask_no_unit, "unit_price"] = d.loc[mask_no_unit, "promo_unit_price"] / (
        1 - d.loc[mask_no_unit, "discount_depth"]
    )

    # Recover missing promo_unit_price from unit_price and discount_depth
    mask_no_promo = (d["promo_unit_price"].isna() | (d["promo_unit_price"] == 0)) & (d["discount_depth"] > 0)
    d.loc[mask_no_promo, "promo_unit_price"] = d.loc[mask_no_promo, "unit_price"] * (
        1 - d.loc[mask_no_promo, "discount_depth"]
    )

    d["price_ratio"] = d["promo_unit_price"] / d["unit_price"].replace({0: np.nan})
    d["log_price_ratio"] = np.log(d["price_ratio"].clip(lower=1e-6))

    d["discount_depth_sq"] = d["discount_depth"] ** 2
    d["promo_duration"] = pd.to_numeric(d["promo_duration"], errors="coerce")

    return d


def add_investment_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["promo_investment"] = pd.to_numeric(d["promo_investment"], errors="coerce")
    d["baseline_volume"] = pd.to_numeric(d["baseline_volume"], errors="coerce")

    d["log_baseline_volume"] = np.log1p(d["baseline_volume"].clip(lower=0))
    d["log_promo_investment"] = np.log1p(d["promo_investment"].clip(lower=0))

    d["gross_margin_pct"] = pd.to_numeric(d["gross_margin_pct"], errors="coerce")
    d["cogs_per_unit"] = pd.to_numeric(d["cogs_per_unit"], errors="coerce")

    return d


def add_promo_pressure(
    df: pd.DataFrame,
    *,
    group_keys: Tuple[str, str, str] = ("market", "retailer", "category"),
    sku_col: str = "sku_id",
) -> pd.DataFrame:
    """
    Cannibalization proxy:
    For each row, compute promo pressure of OTHER SKUs in same market/retailer/category and same promo_week_start.
    pressure = sum(discount_depth of other promos)
    """
    d = df.copy()

    agg = (
        d.groupby(list(group_keys) + ["promo_week_start"], dropna=False)
        .agg(total_discount_pressure=("discount_depth", "sum"), promo_count=("promo_event_id", "count"))
        .reset_index()
    )

    d = d.merge(agg, on=list(group_keys) + ["promo_week_start"], how="left")

    # Remove own contribution approx:
    d["category_promo_pressure"] = (d["total_discount_pressure"] - d["discount_depth"]).fillna(0.0)
    d["category_promo_count_other"] = (d["promo_count"] - 1).clip(lower=0).fillna(0).astype(int)

    # Optional: brand pressure (within brand)
    if "brand" in d.columns:
        agg_b = (
            d.groupby(["market", "retailer", "brand", "promo_week_start"], dropna=False)
            .agg(total_brand_discount_pressure=("discount_depth", "sum"), brand_promo_count=("promo_event_id", "count"))
            .reset_index()
        )
        d = d.merge(agg_b, on=["market", "retailer", "brand", "promo_week_start"], how="left")
        d["brand_promo_pressure"] = (d["total_brand_discount_pressure"] - d["discount_depth"]).fillna(0.0)
        d["brand_promo_count_other"] = (d["brand_promo_count"] - 1).clip(lower=0).fillna(0).astype(int)
    else:
        d["brand_promo_pressure"] = 0.0
        d["brand_promo_count_other"] = 0

    return d


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature engineering for BOTH training and prediction."""
    d = df.copy()

    d = add_time_features(d)
    d = add_price_features(d)
    d = add_investment_features(d)
    d = add_promo_pressure(d)

    d = d.replace([np.inf, -np.inf], np.nan)
    return d


def prepare_training_data(df: pd.DataFrame) -> pd.DataFrame:
    """Training-only: build features + target."""
    d = make_features(df)

    d["incremental_volume"] = pd.to_numeric(d["incremental_volume"], errors="coerce")
    d["y_asinh"] = np.arcsinh(d["incremental_volume"].fillna(0.0))

    required = [
        "y_asinh",
        "discount_depth",
        "promo_duration",
        "log_baseline_volume",
        "log_promo_investment",
        "log_price_ratio",
        "t_weeks",
    ]
    d = d.dropna(subset=required)

    return d


def train_sklearn_model(df: pd.DataFrame, *, model_type: str = "ridge"):
    try:
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.compose import ColumnTransformer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        from sklearn.linear_model import Ridge, ElasticNet
        from sklearn.metrics import mean_absolute_error
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "scikit-learn is required for simulation scoring. Install with `pip install scikit-learn`."
        ) from e

    d = prepare_training_data(df).sort_values("promo_mid_date")
    y = d["y_asinh"].values

    numeric_features = [
        "discount_depth",
        "discount_depth_sq",
        "log_price_ratio",
        "promo_duration",
        "log_baseline_volume",
        "log_promo_investment",
        "gross_margin_pct",
        "category_promo_pressure",
        "brand_promo_pressure",
        "t_weeks",
    ]

    categorical_features = [
        "offer_type",
        "month",
        "iso_week",
        "market",
        "retailer",
        "segment",
        "category",
        "brand",
        "flavor",
        "pack_size",
        "product_group_name",
        "unit_of_measure",
    ]
    categorical_features = [c for c in categorical_features if c in d.columns]

    pre = ColumnTransformer(
        transformers=[
            ("num", "passthrough", numeric_features),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_features),
        ],
        remainder="drop",
    )

    reg = ElasticNet(alpha=0.01, l1_ratio=0.2, max_iter=5000) if model_type == "elasticnet" else Ridge(alpha=10.0)
    pipe = Pipeline(steps=[("pre", pre), ("reg", reg)])

    # optional: TimeSeries CV
    tscv = TimeSeriesSplit(n_splits=5)
    maes = []
    for tr, va in tscv.split(d):
        pipe.fit(d.iloc[tr], y[tr])
        pred = pipe.predict(d.iloc[va])
        maes.append(mean_absolute_error(y[va], pred))

    pipe.fit(d, y)
    return pipe, d, float(np.mean(maes))


def predict_incremental_volume_from_asinh(yhat_asinh: np.ndarray) -> np.ndarray:
    return np.sinh(yhat_asinh)


def predict_incremental_volume_sklearn(pipe, df_new: pd.DataFrame) -> pd.DataFrame:
    """Score candidates, returning a DataFrame aligned with df_new's index.

    Rows that lack required features get NaN for pred_incremental_volume
    instead of being dropped, so the caller always gets back the same
    number of rows as the input.
    """
    dnew = make_features(df_new)

    required = [
        "discount_depth",
        "promo_duration",
        "log_baseline_volume",
        "log_promo_investment",
        "log_price_ratio",
        "t_weeks",
    ]
    missing_cols = [c for c in required if c not in dnew.columns]
    if missing_cols:
        raise ValueError(f"Missing required engineered columns: {missing_cols}")

    scoreable_mask = dnew[required].notna().all(axis=1)
    dnew["pred_incremental_volume"] = np.nan

    if scoreable_mask.any():
        yhat_asinh = pipe.predict(dnew.loc[scoreable_mask])
        dnew.loc[scoreable_mask, "pred_incremental_volume"] = np.sinh(yhat_asinh)
        dnew["pred_incremental_volume"] = dnew["pred_incremental_volume"].clip(lower=0)

    out_cols = [
        c for c in ["promo_event_id", "sku_id", "market", "retailer", "pred_incremental_volume"] if c in dnew.columns
    ]
    return dnew[out_cols]


def compute_roi(df_scored: pd.DataFrame, *, incr_vol_col: str = "pred_incremental_volume") -> pd.DataFrame:
    d = df_scored.copy()

    d["promo_unit_price"] = pd.to_numeric(d.get("promo_unit_price"), errors="coerce")
    d["cogs_per_unit"] = pd.to_numeric(d.get("cogs_per_unit"), errors="coerce")
    d["promo_investment"] = pd.to_numeric(d.get("promo_investment"), errors="coerce")

    d["pred_incr_margin"] = pd.to_numeric(d.get(incr_vol_col), errors="coerce") * (
        d["promo_unit_price"] - d["cogs_per_unit"]
    )
    d["pred_incr_profit"] = d["pred_incr_margin"] - d["promo_investment"]

    inv = d["promo_investment"].replace({0: np.nan})
    d["pred_roi"] = d["pred_incr_profit"] / inv

    return d


def simulate_agent_output_json(*, agent_output_json_path: str | Path, dataset_csv_path: str | Path) -> Tuple[pd.DataFrame, SimulationSummary]:
    json_path = Path(agent_output_json_path)
    dataset_path = Path(dataset_csv_path)

    raw = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None
    if not isinstance(raw, dict) or "promotions" not in raw:
        raise ValueError("agent_output.json must contain a top-level 'promotions' array")

    promotions = raw.get("promotions")
    if not isinstance(promotions, list) or not promotions:
        raise ValueError("agent_output.json has no promotions to simulate")

    df_hist = pd.read_csv(dataset_path)
    pipe, _dtrain, _cv_mae = train_sklearn_model(df_hist, model_type="ridge")

    df_candidates = pd.DataFrame(promotions)
    if "unit_of_measure" not in df_candidates.columns:
        df_candidates["unit_of_measure"] = "EA"
    else:
        df_candidates["unit_of_measure"] = df_candidates["unit_of_measure"].fillna("EA")

    econ_model_output = predict_incremental_volume_sklearn(pipe, df_candidates)
    df_candidates["pred_incremental_volume"] = econ_model_output["pred_incremental_volume"].values
    scored = compute_roi(df_candidates, incr_vol_col="pred_incremental_volume")

    num_scored = int(scored["pred_incremental_volume"].notna().sum())
    if num_scored == 0:
        raise ValueError(
            "No candidates could be scored. Ensure promotions include valid "
            "unit_price, promo_unit_price, discount_depth, and promo dates."
        )

    rois = pd.to_numeric(scored["pred_roi"], errors="coerce")
    valid_rois = rois.dropna()
    summary = SimulationSummary(
        num_candidates_in=int(len(df_candidates)),
        num_candidates_scored=num_scored,
        pred_roi_min=float(np.nanmin(valid_rois.values)) if len(valid_rois) else 0.0,
        pred_roi_max=float(np.nanmax(valid_rois.values)) if len(valid_rois) else 0.0,
        pred_roi_positive_count=int((valid_rois > 0).sum()),
    )

    return scored, summary
