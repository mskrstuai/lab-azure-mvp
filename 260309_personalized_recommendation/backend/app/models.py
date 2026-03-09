from sqlalchemy import Column, Float, Integer, String

from .database import Base


class Article(Base):
    __tablename__ = "articles"

    article_id = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True)
    prod_name = Column(String, nullable=True)
    product_type_name = Column(String, nullable=True)
    product_group_name = Column(String, nullable=True)
    graphical_appearance_name = Column(String, nullable=True)
    colour_group_name = Column(String, nullable=True)
    perceived_colour_value_name = Column(String, nullable=True)
    perceived_colour_master_name = Column(String, nullable=True)
    department_name = Column(String, nullable=True)
    index_name = Column(String, nullable=True)
    index_group_name = Column(String, nullable=True)
    section_name = Column(String, nullable=True)
    garment_group_name = Column(String, nullable=True)
    detail_desc = Column(String, nullable=True)


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(String, primary_key=True, index=True)
    FN = Column(Float, nullable=True)
    Active = Column(Float, nullable=True)
    club_member_status = Column(String, nullable=True)
    fashion_news_frequency = Column(String, nullable=True)
    age = Column(Float, nullable=True)
    postal_code = Column(String, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    t_dat = Column(String, nullable=True)
    customer_id = Column(String, nullable=True, index=True)
    article_id = Column(String, nullable=True, index=True)
    price = Column(Float, nullable=True)
    sales_channel_id = Column(Integer, nullable=True)

