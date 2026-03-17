"""
Data Loader
===========
Loads JSON data files and provides shared access for routers and the orchestrator.
"""

import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_json(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")
    with open(filepath, "r") as f:
        return json.load(f)


customers_data = _load_json("customers.json")
products_data = _load_json("products.json")
similarity_data = _load_json("similarity.json")
inventory_data = _load_json("inventory.json")

customers_by_id = {c["customer_id"]: c for c in customers_data["customers"]}
products_by_id = {p["product_id"]: p for p in products_data["products"]}
similarity_by_id = {s["customer_id"]: s for s in similarity_data["similarity_index"]}
categories = {c["index"]: c for c in products_data["categories"]}


def normalize_customer_id(customer_id: str) -> str:
    if not customer_id.startswith("CG-"):
        return customer_id
    numeric_part = customer_id[3:]
    try:
        num = int(numeric_part)
        return f"CG-{num:04d}"
    except ValueError:
        return customer_id


def get_active_categories(customer: dict) -> list[str]:
    return [
        categories[i]["name"]
        for i, val in enumerate(customer["category_purchases"])
        if val == 1
    ]


def get_summary_stats() -> dict:
    customers = customers_data["customers"]
    orders = sorted([c["total_orders_90d"] for c in customers])
    values = sorted([c["avg_order_value"] for c in customers])
    n = len(customers)
    top_by_orders = max(customers, key=lambda c: c["total_orders_90d"])
    top_by_value = max(customers, key=lambda c: c["avg_order_value"])
    return {
        "total_customers": n,
        "total_products": len(products_data["products"]),
        "avg_orders_90d": round(sum(orders) / n, 1),
        "avg_order_value": round(sum(values) / n, 2),
        "median_orders_90d": orders[n // 2],
        "median_order_value": values[n // 2],
        "top_customer_by_orders": {
            "customer_id": top_by_orders["customer_id"],
            "name": top_by_orders["name"],
            "total_orders_90d": top_by_orders["total_orders_90d"],
            "region": top_by_orders["region"],
        },
        "top_customer_by_avg_value": {
            "customer_id": top_by_value["customer_id"],
            "name": top_by_value["name"],
            "avg_order_value": top_by_value["avg_order_value"],
            "region": top_by_value["region"],
        },
        "regions": list(set(c["region"] for c in customers)),
        "facility_types": list(set(c["type"] for c in customers)),
        "data_notes": [
            "Revenue estimates require historical purchase volume data (not currently tracked)",
            "Confidence scores reflect likelihood of interest, NOT expected purchase volume",
            "Similarity is based on Jaccard index of category purchases",
            "'Biggest' can mean highest orders OR highest average value - clarify with user",
        ],
    }


def list_customers(
    region: Optional[str] = None,
    type: Optional[str] = None,
    sort_by: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    results = []
    for c in customers_data["customers"]:
        if region and c["region"] != region:
            continue
        if type and c["type"] != type:
            continue
        results.append(
            {
                "customer_id": c["customer_id"],
                "name": c["name"],
                "type": c["type"],
                "region": c["region"],
                "size": c["size"],
                "total_orders_90d": c["total_orders_90d"],
                "avg_order_value": c["avg_order_value"],
                "active_categories": get_active_categories(c),
            }
        )
    if sort_by:
        descending = sort_by.startswith("-")
        field = sort_by.lstrip("-")
        valid = ["total_orders_90d", "avg_order_value", "name"]
        if field in valid:
            results.sort(key=lambda x: x[field], reverse=descending)
    return results[:limit]


def get_customer_profile(customer_id: str) -> Optional[dict]:
    customer_id = normalize_customer_id(customer_id)
    c = customers_by_id.get(customer_id)
    if not c:
        return None
    return {
        "customer_id": c["customer_id"],
        "name": c["name"],
        "type": c["type"],
        "region": c["region"],
        "size": c["size"],
        "total_orders_90d": c["total_orders_90d"],
        "avg_order_value": c["avg_order_value"],
        "active_categories": get_active_categories(c),
    }


def get_similar_customers(
    customer_id: str,
    limit: int = 5,
    min_similarity: float = 0.5,
    include_ci: bool = True,
) -> Optional[list[dict]]:
    from .similarity_model import get_model

    customer_id = normalize_customer_id(customer_id)
    if customer_id not in customers_by_id:
        return None
    model = get_model()
    neighbors = model.get_similar_customers(
        customer_id,
        limit=limit,
        min_similarity=min_similarity,
        include_confidence_interval=include_ci,
    )
    results = []
    for neighbor in neighbors:
        profile = customers_by_id.get(neighbor["customer_id"])
        if not profile:
            continue
        results.append(
            {
                "customer_id": neighbor["customer_id"],
                "name": profile["name"],
                "similarity": neighbor["similarity"],
                "shared_categories": neighbor["shared_categories"],
                "type": profile["type"],
                "region": profile["region"],
                "confidence_interval_95": neighbor.get("confidence_interval_95"),
            }
        )
    return results


def get_product_recommendations(customer_id: str, limit: int = 10) -> Optional[list[dict]]:
    customer_id = normalize_customer_id(customer_id)
    if customer_id not in customers_by_id:
        return None
    customer = customers_by_id[customer_id]
    customer_categories = set(
        i for i, val in enumerate(customer["category_purchases"]) if val == 1
    )
    if customer_id not in similarity_by_id:
        return []
    sim_data = similarity_by_id[customer_id]
    category_scores: dict[int, float] = {}
    for neighbor in sim_data["neighbors"][:5]:
        neighbor_profile = customers_by_id.get(neighbor["customer_id"])
        if not neighbor_profile:
            continue
        neighbor_cats = set(
            i for i, val in enumerate(neighbor_profile["category_purchases"]) if val == 1
        )
        for cat_idx in neighbor_cats - customer_categories:
            category_scores[cat_idx] = category_scores.get(cat_idx, 0) + neighbor["similarity"]
    sorted_cats = sorted(category_scores.items(), key=lambda x: -x[1])
    recommendations = []
    for cat_idx, score in sorted_cats[:limit]:
        cat_name = categories[cat_idx]["name"]
        for product in products_data["products"]:
            if product["category_index"] == cat_idx:
                similar_count = len(
                    [
                        n
                        for n in sim_data["neighbors"][:5]
                        if cat_idx
                        in set(
                            i
                            for i, v in enumerate(
                                customers_by_id.get(n["customer_id"], {}).get(
                                    "category_purchases", []
                                )
                            )
                            if v == 1
                        )
                    ]
                )
                recommendations.append(
                    {
                        "product_id": product["product_id"],
                        "name": product["name"],
                        "category": cat_name,
                        "unit_price": product["unit_price"],
                        "reason": f"Purchased by {similar_count} similar customers",
                        "confidence": min(score / 2, 0.95),
                    }
                )
                break
        if len(recommendations) >= limit:
            break
    return recommendations


def get_inventory_alerts() -> list[dict]:
    return [
        {
            "alert_id": a["alert_id"],
            "type": a["type"],
            "region": a["region"],
            "message": a["message"],
            "products_affected": a["products_affected"],
        }
        for a in inventory_data.get("alerts", [])
    ]


def get_regional_inventory(region: str) -> Optional[list[dict]]:
    for r in inventory_data["regions"]:
        if r["region"] == region:
            return [
                {
                    "product_id": p["product_id"],
                    "name": products_by_id.get(p["product_id"], {}).get("name", "Unknown"),
                    "region": region,
                    "stock_level": p["stock_level"],
                    "status": p["status"],
                    "days_of_supply": p["days_of_supply"],
                }
                for p in r["products"]
            ]
    return None
