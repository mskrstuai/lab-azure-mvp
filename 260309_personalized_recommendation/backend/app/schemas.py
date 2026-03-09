from typing import Optional

from pydantic import BaseModel


class ArticleBase(BaseModel):
    article_id: str
    product_code: Optional[str] = None
    prod_name: Optional[str] = None
    product_type_name: Optional[str] = None
    product_group_name: Optional[str] = None
    graphical_appearance_name: Optional[str] = None
    colour_group_name: Optional[str] = None
    perceived_colour_value_name: Optional[str] = None
    perceived_colour_master_name: Optional[str] = None
    department_name: Optional[str] = None
    index_name: Optional[str] = None
    index_group_name: Optional[str] = None
    section_name: Optional[str] = None
    garment_group_name: Optional[str] = None
    detail_desc: Optional[str] = None
    image_url: Optional[str] = None


class Article(ArticleBase):
    class Config:
        from_attributes = True


class CustomerBase(BaseModel):
    customer_id: str
    FN: Optional[float] = None
    Active: Optional[float] = None
    club_member_status: Optional[str] = None
    fashion_news_frequency: Optional[str] = None
    age: Optional[float] = None
    postal_code: Optional[str] = None


class Customer(CustomerBase):
    class Config:
        from_attributes = True


class TransactionBase(BaseModel):
    id: int
    t_dat: Optional[str] = None
    customer_id: Optional[str] = None
    article_id: Optional[str] = None
    price: Optional[float] = None
    sales_channel_id: Optional[int] = None


class Transaction(TransactionBase):
    class Config:
        from_attributes = True


class TransactionItem(BaseModel):
    article_id: Optional[str] = None
    price: Optional[float] = None
    sales_channel_id: Optional[int] = None
    article: Optional[Article] = None


class TransactionGroup(BaseModel):
    t_dat: str
    customer_id: str
    items: list[TransactionItem] = []


class ChatMessage(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
