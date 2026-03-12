from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """Single search result with all scoring components."""

    document: dict

    position: Optional[int] = Field(
        default=None,
        description="1-based display position. 'first item' = position 1, 'second item' = position 2, etc.",
    )

    search_score: Optional[float] = None
    reranker_score: Optional[float] = None
    captions: Optional[list] = None

    rs_score: Optional[float] = None
    rs_model: Optional[Literal["two_stage", "als_cf"]] = None

    final_score: Optional[float] = None

    search_rank: Optional[int] = None
    rs_rank: Optional[int] = None
    final_rank: Optional[int] = None

    @property
    def article_id(self) -> Optional[str]:
        return self.document.get("Id")

    @property
    def effective_search_score(self) -> float:
        if self.reranker_score is not None:
            return self.reranker_score
        return self.search_score or 0.0


class SearchResponse(BaseModel):
    """Search response containing results and optional facets."""

    results: List[SearchResult] = Field(default_factory=list)
    facets: Optional[dict] = None
    total_count: int = 0

    is_reranked: bool = False
    reranking_model: Optional[str] = None

    def format_for_llm(self) -> str:
        """
        Format results for LLM consumption so product_id (Id) is explicit.
        Prevents LLM from confusing result index/rank with article Id.
        """
        if not self.results:
            return "No results found."
        lines = [
            f"Search results ({len(self.results)} items). "
            "IMPORTANT: Use the product_id (Id) when calling get_product_by_id or more_like_this - NOT the position number."
        ]
        for i, r in enumerate(self.results, 1):
            aid = r.document.get("Id")
            name = r.document.get("ProductName", "")
            ptype = r.document.get("ProductTypeName", "")
            color = r.document.get("ColourGroupName", "")
            lines.append(
                f"  {i}. product_id={aid!r} | {name} | {ptype} | {color}"
            )
        return "\n".join(lines)


class ItemsVectorFields(BaseModel):
    """Vector field names for items in the search index."""

    verbalised_desc_vector: str = "VerbalisedDescVector"
    overall_desc_vector: str = "OverallDescVector"

    @property
    def all_fields(self) -> List[str]:
        return [v for v in [self.verbalised_desc_vector, self.overall_desc_vector] if v]


class ItemsSelectFields(BaseModel):
    """Select field names for items in the search index."""

    id: str = "Id"
    product_code: str = "ProductCode"
    product_name: str = "ProductName"
    product_type_no: str = "ProductTypeNo"
    product_type_name: str = "ProductTypeName"
    product_group_name: str = "ProductGroupName"
    graphical_appearance_no: str = "GraphicalAppearanceNo"
    graphical_appearance_name: str = "GraphicalAppearanceName"
    colour_group_code: str = "ColourGroupCode"
    colour_group_name: str = "ColourGroupName"
    perceived_colour_value_id: str = "PerceivedColourValueId"
    perceived_colour_value_name: str = "PerceivedColourValueName"
    perceived_colour_master_id: str = "PerceivedColourMasterId"
    perceived_colour_master_name: str = "PerceivedColourMasterName"
    department_no: str = "DepartmentNo"
    department_name: str = "DepartmentName"
    index_code: str = "IndexCode"
    index_name: str = "IndexName"
    index_group_no: str = "IndexGroupNo"
    index_group_name: str = "IndexGroupName"
    section_no: str = "SectionNo"
    section_name: str = "SectionName"
    garment_group_no: str = "GarmentGroupNo"
    garment_group_name: str = "GarmentGroupName"
    detail_desc: str = "DetailDesc"
    overall_desc: str = "OverallDesc"
    verbalised_desc: str = "VerbalisedDesc"

    @property
    def all_fields(self) -> List[str]:
        return [v for v in self.__dict__.values() if isinstance(v, str)]


class ItemDetectionVectorFields(BaseModel):
    """Vector field names for items in the item detection category based search index."""

    product_group_name_vector: str = "ProductGroupNameVector"
    combined_metadata_vector: str = "CombinedMetadataVector"

    @property
    def all_fields(self) -> List[str]:
        return [v for v in [self.product_group_name_vector, self.combined_metadata_vector] if v]
