from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


def load_to_sqlite(data_dir: Path, db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}")

    articles = pd.read_csv(data_dir / "articles.csv", dtype={"article_id": str, "product_code": str})
    customers = pd.read_csv(data_dir / "customers.csv", dtype={"customer_id": str, "postal_code": str})
    transactions = pd.read_csv(
        data_dir / "transactions_train.csv", dtype={"customer_id": str, "article_id": str}
    )

    articles.to_sql("articles", engine, if_exists="replace", index=False)
    customers.to_sql("customers", engine, if_exists="replace", index=False)
    transactions.to_sql("transactions", engine, if_exists="replace", index=False)

    print(f"Loaded SQLite DB at: {db_path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    dataset_dir = root.parent / "data"
    sqlite_path = root / "hm.db"
    load_to_sqlite(dataset_dir, sqlite_path)
