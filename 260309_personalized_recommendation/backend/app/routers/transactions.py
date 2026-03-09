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
