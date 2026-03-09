from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[schemas.Transaction])
def list_transactions(
    limit: int = 50,
    offset: int = 0,
    customer_id: Optional[str] = Query(None, description="Filter by customer ID (exact match)"),
    db: Session = Depends(get_db),
):
    return crud.get_transactions(db, limit=limit, offset=offset, customer_id=customer_id)


@router.get("/grouped", response_model=list[schemas.TransactionGroup])
def list_transactions_grouped(
    limit: int = 100,
    offset: int = 0,
    customer_id: Optional[str] = Query(None, description="Filter by customer ID (exact match)"),
    db: Session = Depends(get_db),
):
    """Return transactions grouped by date and customer, with article details."""
    return crud.get_transactions_grouped(db, limit=limit, offset=offset, customer_id=customer_id)
