"""
Personalized Shopping Assistant Agent Package

This package provides a personalized shopping assistant agent built on Semantic Kernel.
It includes Azure AI Search integration, recommender system-based reranking, and
user preference handling for personalized product recommendations.
"""

from .personalized_shopping_assistant import PersonalizedShoppingAssistant
from .helpers.image_renderer import ImageRenderer, display_product_images
from .models import (
    UserPreferences,
    SearchQuery,
    ProductResult,
    SearchResult,
    SearchResponse,
    SearchMemory,
    PreferencesType,
    RankingModel,
)

__all__ = [
    "PersonalizedShoppingAssistant",
    "ImageRenderer",
    "display_product_images",
    "UserPreferences",
    "SearchQuery",
    "ProductResult",
    "SearchResult",
    "SearchResponse",
    "SearchMemory",
    "PreferencesType",
    "RankingModel",
]

__version__ = "0.1.0"
