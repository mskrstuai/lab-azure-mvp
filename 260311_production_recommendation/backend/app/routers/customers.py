"""Customer and recommendation API endpoints."""

from typing import Optional
from fastapi import APIRouter, HTTPException

from ..data_loader import (
    get_summary_stats,
    list_customers,
    get_customer_profile,
    get_similar_customers,
    get_product_recommendations,
)

router = APIRouter()


@router.get("/stats/summary")
async def summary_stats():
    return get_summary_stats()


@router.get("/customers")
async def customers_list(
    region: Optional[str] = None,
    type: Optional[str] = None,
    sort_by: Optional[str] = None,
    limit: int = 20,
):
    return list_customers(region=region, type=type, sort_by=sort_by, limit=limit)


@router.get("/customers/{customer_id}")
async def customer_detail(customer_id: str):
    profile = get_customer_profile(customer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return profile


@router.get("/customers/{customer_id}/similar")
async def similar_customers(
    customer_id: str,
    limit: int = 5,
    min_similarity: float = 0.5,
    include_ci: bool = True,
):
    results = get_similar_customers(
        customer_id, limit=limit, min_similarity=min_similarity, include_ci=include_ci
    )
    if results is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return results


@router.get("/customers/{customer_id}/recommendations")
async def recommendations(customer_id: str, limit: int = 10):
    results = get_product_recommendations(customer_id, limit=limit)
    if results is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return results
