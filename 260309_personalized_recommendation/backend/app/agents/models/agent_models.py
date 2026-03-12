from typing import List, Dict, Optional

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    """
    User preference profile loaded from processed preferences files.
    """

    user_id: str
    overall_summary: str = ""
    short_term_summary: str = ""
    category_summaries: Dict[str, str] = Field(default_factory=dict)
    total_transactions: int = 0
    is_loaded: bool = False


class SearchQuery(BaseModel):
    """
    Constructed search query combining all signals.
    """

    raw_query: str
    enhanced_query: str
    detected_category: Optional[str] = None
    detected_colors: List[str] = Field(default_factory=list)
    filters: Dict[str, str] = Field(default_factory=dict)
    preferences_context: str = ""
    chat_context: str = ""


class ProductResult(BaseModel):
    """
    A single product from search results.
    """

    id: str
    name: str
    product_type: str
    product_group: str
    department: str
    color: str
    description: str

    search_score: float = 0.0
    reranker_score: Optional[float] = None

    raw_data: Dict = Field(default_factory=dict)
