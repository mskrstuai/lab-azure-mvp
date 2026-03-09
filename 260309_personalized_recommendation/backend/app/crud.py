from typing import Optional

from sqlalchemy.orm import Session

from . import models


def _article_with_image(article: models.Article):
    article_id = str(article.article_id).zfill(10)
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


def get_articles(db: Session, limit: int = 50, offset: int = 0):
    rows = db.query(models.Article).offset(offset).limit(limit).all()
    return [_article_with_image(row) for row in rows]


def get_article(db: Session, article_id: str) -> Optional[dict]:
    row = db.query(models.Article).filter(models.Article.article_id == article_id).first()
    if not row:
        return None
    return _article_with_image(row)


def get_customers(db: Session, limit: int = 50, offset: int = 0):
    return db.query(models.Customer).offset(offset).limit(limit).all()


def get_customer(db: Session, customer_id: str):
    return db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()


def get_transactions(db: Session, limit: int = 50, offset: int = 0):
    return db.query(models.Transaction).offset(offset).limit(limit).all()
