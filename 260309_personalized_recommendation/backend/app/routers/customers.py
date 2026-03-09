from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[schemas.Customer])
def list_customers(
    limit: int = 50,
    offset: int = 0,
    customer_id: Optional[str] = Query(None, description="Filter by customer ID (partial match)"),
    db: Session = Depends(get_db),
):
    return crud.get_customers(db, limit=limit, offset=offset, customer_id=customer_id)


@router.get("/{customer_id}", response_model=schemas.Customer)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = crud.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
