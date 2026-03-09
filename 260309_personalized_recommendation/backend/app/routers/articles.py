from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=list[schemas.Article])
def list_articles(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return crud.get_articles(db, limit=limit, offset=offset)


@router.get("/{article_id}", response_model=schemas.Article)
def get_article(article_id: str, db: Session = Depends(get_db)):
    article = crud.get_article(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
