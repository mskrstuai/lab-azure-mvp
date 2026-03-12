import os
from typing import ClassVar, Optional

from semantic_kernel.kernel_pydantic import KernelBaseSettings


class DataSettings(KernelBaseSettings):
    """
    Data settings with support for multiple runtime environments.
    """

    env_prefix: ClassVar[str] = "DATA_"

    skip_managed_identity_auth: bool = False

    storage_account_name: str = ""
    raw_data_path: str = ""
    processed_data_path: str = ""
    output_data_path: Optional[str] = None
    recommender_models_path: str = ""
    recommender_models_container: str = ""

    block_overall_preferences_summary_subdir: str = "blocks_overall_preferences_summaries"
    block_category_preferences_summary_subdir: str = "blocks_category_preferences_summaries"
    block_short_term_preferences_summary_subdir: str = "blocks_short_term_preferences_summaries"
    final_overall_preferences_summary_subdir: str = "final_overall_preferences_summaries"
    final_category_preferences_summary_subdir: str = "final_category_preferences_summaries"
    final_short_term_preferences_summary_subdir: str = "final_short_term_preferences_summaries"

    transactions_raw_file: str = "transactions_train.csv"
    products_metadata_raw_file: str = "articles.csv"
    users_metadata_raw_file: str = "customers.csv"
    transactions_processed_file: str = "transactions_enriched.parquet"
    transactions_processed_file_sample: str = "transactions_enriched_sample.parquet"
    products_metadata_processed_file: str = "articles_enriched.csv"
    users_metadata_processed_file: str = "customers_sampled.csv"

    two_stage_top100_file: str = "two_stage_top100_latest.parquet"
    als_cf_model_file: str = "als_1000_users_all_items.parquet"

    @property
    def effective_output_path(self) -> str:
        return self.output_data_path or self.processed_data_path
