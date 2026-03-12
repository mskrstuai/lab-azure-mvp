from fastapi import APIRouter, HTTPException

from ..services.local_preferences import get_preferences, list_preference_customers

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/customers")
def list_customers():
    """List customer IDs that have preferences (from final_overall + final_short_term)."""
    customers = list_preference_customers()
    return {"customers": customers}


@router.get("/customers/{customer_id}")
def get_customer_preferences(customer_id: str):
    """Get overall_summary and short_term_summary for a customer."""
    prefs = get_preferences(customer_id)
    if prefs is None:
        raise HTTPException(status_code=404, detail="Customer preferences not found")
    return prefs
