from typing import ClassVar, List, Optional

from semantic_kernel.kernel_pydantic import KernelBaseSettings
from ..models.search import (
    ItemsVectorFields,
    ItemsSelectFields,
    ItemDetectionVectorFields,
)


class AzureSearchSettings(KernelBaseSettings):
    env_prefix: ClassVar[str] = "AZURE_SEARCH_"

    endpoint: str
    api_key: Optional[str] = None
    key: Optional[str] = None

    index_name_items: str = "articles-processed-index"
    index_name_preferences: str = "customer-preferences-index"
    index_name_item_detection: str = "item-detection-index"
    semantic_configuration_name: str = "my-semantic-config-default"
    filter_missing_images: bool = True

    vector_fields_items: ItemsVectorFields = ItemsVectorFields()
    select_fields_items: ItemsSelectFields = ItemsSelectFields()

    vector_fields_item_detection: ItemDetectionVectorFields = ItemDetectionVectorFields()
    select_fields_item_detection: List[str] = [
        "Id",
        "ProductName",
        "ProductTypeName",
        "ProductGroupName",
        "DepartmentName",
        "IndexName",
        "IndexGroupName",
        "SectionName",
        "GarmentGroupName",
        "CombinedMetadata",
    ]

    select_fields_customer_preferences: List[str] = [
        "CustomerId",
        "FinalSummary",
        "PreferenceType",
        "Category",
        "FinalSummaryVector",
    ]

    facet_fields: List[str] = [
        "DepartmentName",
        "ProductTypeName",
        "ColourGroupName",
        "PerceivedColourMasterName",
        "IndexName",
    ]

    filterable_fields: List[str] = [
        "ProductTypeName",
        "DepartmentName",
        "IndexName",
        "GraphicalAppearanceName",
        "PerceivedColourMasterName",
        "PerceivedColourValueName",
        "ColourGroupName",
        "SectionName",
        "GarmentGroupName",
        "ProductGroupName",
    ]

    item_detection_filter_fields: List[str] = ["ProductGroupName"]
