"""Inventory and product API endpoints."""

from fastapi import APIRouter, HTTPException

from ..data_loader import (
    get_inventory_alerts,
    get_regional_inventory,
    products_data,
    products_by_id,
)

router = APIRouter()


@router.get("/inventory/alerts")
async def alerts():
    return get_inventory_alerts()


@router.get("/inventory/{region}")
async def regional_inventory(region: str):
    result = get_regional_inventory(region)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Region {region} not found")
    return result


@router.get("/products/categories")
async def product_categories():
    return products_data["categories"]


@router.get("/products/{product_id}")
async def product_detail(product_id: str):
    if product_id not in products_by_id:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    return products_by_id[product_id]
