from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[schemas.Transaction])
def list_transactions(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return crud.get_transactions(db, limit=limit, offset=offset)
