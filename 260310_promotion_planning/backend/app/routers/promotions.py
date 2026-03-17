"""Promotions API router."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import schemas
from ..data_loader import get_filter_options, get_stats, load_promotions_df

router = APIRouter(prefix="/promotions", tags=["promotions"])

FILTER_COLS = ["market", "retailer", "segment", "category", "brand", "offer_type"]


@router.get("")
def list_promotions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    market: Optional[str] = Query(None),
    retailer: Optional[str] = Query(None),
    segment: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    offer_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Search in sku_description, brand, sku_id"),
):
    """List promotions with optional filters and pagination."""
    df = load_promotions_df()

    # Apply filters
    if market:
        df = df[df["market"] == market]
    if retailer:
        df = df[df["retailer"] == retailer]
    if segment:
        df = df[df["segment"] == segment]
    if category:
        df = df[df["category"] == category]
    if brand:
        df = df[df["brand"] == brand]
    if offer_type:
        df = df[df["offer_type"] == offer_type]

    if search:
        search_lower = search.lower()
        mask = (
            df["sku_description"].fillna("").str.lower().str.contains(search_lower, regex=False)
            | df["brand"].fillna("").str.lower().str.contains(search_lower, regex=False)
            | df["sku_id"].fillna("").str.lower().str.contains(search_lower, regex=False)
        )
        df = df[mask]

    total = len(df)
    df_page = df.iloc[offset : offset + limit]

    rows = [schemas.promotion_row_to_dict(row) for _, row in df_page.iterrows()]
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options")
def filter_options():
    """Return unique values for filter dropdowns."""
    return get_filter_options()


@router.get("/stats")
def stats():
    """Return aggregate statistics for dashboard."""
    return get_stats()


@router.get("/{promo_event_id}")
def get_promotion(promo_event_id: str):
    """Get a single promotion by promo_event_id."""
    df = load_promotions_df()
    match = df[df["promo_event_id"] == promo_event_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return schemas.promotion_row_to_dict(match.iloc[0])
