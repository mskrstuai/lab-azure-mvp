from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[schemas.Chat])
def list_chats(
    limit: int = 50,
    offset: int = 0,
    customer_id: Optional[str] = Query(None, description="Filter by customer ID"),
    db: Session = Depends(get_db),
):
    return crud.get_chats(db, limit=limit, offset=offset, customer_id=customer_id)


@router.post("", response_model=schemas.Chat, status_code=201)
def create_chat(body: schemas.ChatCreate, db: Session = Depends(get_db)):
    return crud.create_chat(
        db,
        customer_id=body.customer_id,
        message=body.message,
        sender=body.sender,
    )
