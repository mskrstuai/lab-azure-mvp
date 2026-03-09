from typing import Optional

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from . import models

ARTICLE_ID_LENGTH = 10


def _article_with_image(article: models.Article):
    article_id = str(article.article_id).zfill(ARTICLE_ID_LENGTH)
    image_url = f"/images/{article_id[:3]}/{article_id}.jpg"
    return {
        "article_id": str(article.article_id),
        "product_code": article.product_code,
        "prod_name": article.prod_name,
        "product_type_name": article.product_type_name,
        "product_group_name": article.product_group_name,
        "graphical_appearance_name": article.graphical_appearance_name,
        "colour_group_name": article.colour_group_name,
        "perceived_colour_value_name": article.perceived_colour_value_name,
        "perceived_colour_master_name": article.perceived_colour_master_name,
        "department_name": article.department_name,
        "index_name": article.index_name,
        "index_group_name": article.index_group_name,
        "section_name": article.section_name,
        "garment_group_name": article.garment_group_name,
        "detail_desc": article.detail_desc,
        "image_url": image_url,
    }


def get_articles(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    prod_name: Optional[str] = None,
    index_group_name: Optional[str] = None,
    product_type_name: Optional[str] = None,
    product_group_name: Optional[str] = None,
    colour_group_name: Optional[str] = None,
    section_name: Optional[str] = None,
    garment_group_name: Optional[str] = None,
):
    query = db.query(models.Article)
    if prod_name:
        query = query.filter(models.Article.prod_name.ilike(f"%{prod_name}%"))
    if index_group_name:
        query = query.filter(models.Article.index_group_name == index_group_name)
    if product_type_name:
        query = query.filter(models.Article.product_type_name == product_type_name)
    if product_group_name:
        query = query.filter(models.Article.product_group_name == product_group_name)
    if colour_group_name:
        query = query.filter(models.Article.colour_group_name == colour_group_name)
    if section_name:
        query = query.filter(models.Article.section_name == section_name)
    if garment_group_name:
        query = query.filter(models.Article.garment_group_name == garment_group_name)
    rows = query.offset(offset).limit(limit).all()
    return [_article_with_image(row) for row in rows]


def get_article(db: Session, article_id: str) -> Optional[dict]:
    row = db.query(models.Article).filter(models.Article.article_id == article_id).first()
    if not row:
        return None
    return _article_with_image(row)


def get_article_filter_options(db: Session):
    def _distinct_values(column):
        rows = db.query(distinct(column)).filter(column.isnot(None)).order_by(column).all()
        return [r[0] for r in rows]

    return {
        "index_group_name": _distinct_values(models.Article.index_group_name),
        "product_type_name": _distinct_values(models.Article.product_type_name),
        "product_group_name": _distinct_values(models.Article.product_group_name),
        "colour_group_name": _distinct_values(models.Article.colour_group_name),
        "section_name": _distinct_values(models.Article.section_name),
        "garment_group_name": _distinct_values(models.Article.garment_group_name),
    }


def get_customers(db: Session, limit: int = 50, offset: int = 0):
    return db.query(models.Customer).offset(offset).limit(limit).all()


def get_customer(db: Session, customer_id: str):
    return db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()


def get_transactions(db: Session, limit: int = 50, offset: int = 0):
    return db.query(models.Transaction).offset(offset).limit(limit).all()
