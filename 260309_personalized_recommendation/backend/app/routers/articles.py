from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=list[schemas.Article])
def list_articles(
    limit: int = 50,
    offset: int = 0,
    prod_name: Optional[str] = Query(None, description="Search by product name (partial match)"),
    index_group_name: Optional[str] = Query(None, description="Filter by index group (gender)"),
    product_type_name: Optional[str] = Query(None, description="Filter by product type"),
    product_group_name: Optional[str] = Query(None, description="Filter by product group"),
    colour_group_name: Optional[str] = Query(None, description="Filter by colour group"),
    section_name: Optional[str] = Query(None, description="Filter by section"),
    garment_group_name: Optional[str] = Query(None, description="Filter by garment group"),
    db: Session = Depends(get_db),
):
    return crud.get_articles(
        db,
        limit=limit,
        offset=offset,
        prod_name=prod_name,
        index_group_name=index_group_name,
        product_type_name=product_type_name,
        product_group_name=product_group_name,
        colour_group_name=colour_group_name,
        section_name=section_name,
        garment_group_name=garment_group_name,
    )


@router.get("/filter-options")
def get_filter_options(db: Session = Depends(get_db)):
    return crud.get_article_filter_options(db)


@router.get("/{article_id}", response_model=schemas.Article)
def get_article(article_id: str, db: Session = Depends(get_db)):
    article = crud.get_article(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
