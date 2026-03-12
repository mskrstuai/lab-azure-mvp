from __future__ import annotations

import logging
from typing import Annotated, Optional

from semantic_kernel.functions import kernel_function

from ..helpers.image_renderer import ImageRenderer
from ..models.search import SearchResponse
from ..helpers.ai_search_ops import (
    search,
    search_by_filter,
    search_by_vector,
    search_by_text_vector,
)
from ..services.azure_ai_search_service import AzureAiSearchSingleton
from ..services.ranking_service import RankingService
from ..settings.azure_ai_search_settings import AzureSearchSettings
from ..models.const import RankingModel
from ..settings.ranking_settings import RankingSettings

logger = logging.getLogger(__name__)


class SearchPlugin:
    """
    Product search plugin for the personalized search agent.

    RS-based reranking is ALWAYS applied when user_id is available.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
    ):
        self._settings = AzureSearchSettings()
        self._client = AzureAiSearchSingleton.get_client(
            index_name=self._settings.index_name_items
        )
        self._ranking_settings = RankingSettings()
        self._item_detection_client = AzureAiSearchSingleton.get_client(
            index_name=self._settings.index_name_item_detection
        )
        self._user_id = user_id
        self._filter_missing_images = self._settings.filter_missing_images
        self._image_renderer = ImageRenderer() if self._filter_missing_images else None
        self._ranking_service: Optional[RankingService] = None
        if user_id:
            self._ranking_service = RankingService(
                user_id=user_id,
                config=self._ranking_settings,
            )

    def _filter_results_with_images(self, response: SearchResponse) -> SearchResponse:
        if not self._filter_missing_images or not self._image_renderer:
            return response

        if not response.results:
            return response

        filtered_results = []
        for result in response.results:
            article_id = result.document.get("Id")
            if article_id and self._image_renderer.image_exists(article_id):
                filtered_results.append(result)

        return SearchResponse(
            results=filtered_results,
            facets=response.facets,
            total_count=len(filtered_results),
        )

    @kernel_function(
        name="search_products",
        description="""
            Hybrid semantic+vector search over the articles index.

            Use use_rs_candidate_filter=True when the user wants open-ended 
            personalized recommendations without specific product criteria 
            (e.g., "recommend something for me", "what should I buy?", 
            "show me things I might like based on my preferences").

            Use use_rs_candidate_filter=False (default) when the user has 
            specific search criteria or product requirements (e.g., "red dress", 
            "winter boots size 10", "blue cotton shirt").
        """,
    )
    async def search_products(
        self,
        query: Annotated[str, "Final search query"],
        item_detection_filter: Annotated[str, "Item detection filter to apply"],
        use_rs_candidate_filter: Annotated[
            bool,
            "Whether to limit results to top RS-recommended candidates. "
            "Set True for open recommendation queries like 'recommend something for me', 'what should I buy?', 'show me things I might like'"
            "False for specific searches like 'red dress', 'winter boots size 10', 'blue cotton shirt'.",
        ] = False,
    ) -> SearchResponse:
        query = (query or "").strip()
        if not query:
            return SearchResponse(results=[], facets=None, total_count=0)

        logger.info(f"Running product search with query: {query}")

        candidate_filter = None
        query_filter = None

        rs_model = self._ranking_settings.default_ranking_model

        if use_rs_candidate_filter and self._ranking_service:
            candidate_filter = self._ranking_service.get_candidate_filter()
            logger.info(f"Using RS candidate filter with {candidate_filter} products")
            if candidate_filter:
                rs_model = RankingModel.TWO_STAGE

        if not item_detection_filter:
            if candidate_filter:
                query_filter = candidate_filter
            logger.info(f"using query filter = {query_filter}")
        else:
            query_filter = (
                item_detection_filter
                if not candidate_filter
                else item_detection_filter + " and " + candidate_filter
            )
            logger.info(f"using query filter = {query_filter}")

        results = await search(
            self._client,
            search_text=query,
            vectorize_text=True,
            vector_fields=[self._settings.vector_fields_items.verbalised_desc_vector],
            select=self._settings.select_fields_items.all_fields,
            top=10 if not candidate_filter else 100,
            semantic_configuration_name=self._settings.semantic_configuration_name,
            filter=query_filter,
        )

        if (
            self._ranking_service
            and results.results
            and self._ranking_settings.apply_rerank
        ):
            results = self._ranking_service.rerank_response(
                results, model=rs_model, apply_rs_rerank=True
            )
            logger.info(
                f"Reranked {len(results.results)} results using {rs_model} model"
            )

        filtered = self._filter_results_with_images(results)

        return filtered

    @kernel_function(
        name="get_product_by_id",
        description="Fetch one product document by Id. Use the product_id (Id) from search results - e.g. '466595024'. NEVER use position/rank (1, 2, 3).",
    )
    async def get_product_by_id(
        self,
        product_id: Annotated[str, "Article Id from search result (e.g. '466595024'). NOT the result position/rank."],
    ) -> SearchResponse:
        escaped_id = product_id.replace("'", "''")

        return await search_by_filter(
            self._client,
            filter=f"Id eq '{escaped_id}'",
            select=self._settings.select_fields_items.all_fields,
            top=1,
        )

    @kernel_function(
        name="more_like_this",
        description="Find similar items to a given product. Use the product_id (Id) from search results - e.g. '466595024'. NEVER use position/rank (1, 2, 3).",
    )
    async def more_like_this(
        self,
        product_id: Annotated[str, "Article Id from search result (e.g. '466595024'). NOT the result position/rank."],
        top: Annotated[int, "Number of similar results"] = 10,
    ) -> SearchResponse:
        vector_field = self._settings.vector_fields_items.verbalised_desc_vector

        # Try Id as-is first; index may use 10-digit zero-padded format (e.g. 0540485720)
        ids_to_try = [product_id]
        if len(product_id) < 10 and product_id.isdigit():
            ids_to_try.append(product_id.zfill(10))
        elif len(product_id) == 10 and product_id.startswith("0"):
            ids_to_try.insert(0, str(int(product_id)))  # try without leading zeros

        seed_response = None
        used_id = None
        for tid in ids_to_try:
            tid_escaped = tid.replace("'", "''")
            seed_response = await search_by_filter(
                self._client,
                filter=f"Id eq '{tid_escaped}'",
                select=[*self._settings.select_fields_items.all_fields, vector_field],
                top=1,
            )
            if seed_response.results:
                used_id = tid
                break

        if not seed_response or not seed_response.results:
            logger.warning(f"more_like_this: seed product_id={product_id!r} not found in index (tried {ids_to_try})")
            return SearchResponse(results=[], facets=None, total_count=0)

        escaped_id = used_id.replace("'", "''")

        seed_vector = seed_response.results[0].document.get(vector_field)
        if not seed_vector:
            logger.warning(f"more_like_this: seed product_id={product_id!r} has no vector")
            return SearchResponse(results=[], facets=None, total_count=0)

        fetch_top = top * 2 if self._filter_missing_images else top

        results = await search_by_vector(
            self._client,
            vector=seed_vector,
            vector_field=vector_field,
            filter=f"Id ne '{escaped_id}'",
            select=self._settings.select_fields_items.all_fields,
            top=fetch_top,
        )

        logger.info(f"more_like_this: vector search returned {len(results.results)} results for product_id={product_id!r}")

        filtered = self._filter_results_with_images(results)

        if len(filtered.results) < len(results.results):
            logger.info(f"more_like_this: after image filter: {len(filtered.results)} results (was {len(results.results)})")

        if len(filtered.results) > top:
            filtered = SearchResponse(
                results=filtered.results[:top], facets=filtered.facets, total_count=top
            )

        return filtered

    @kernel_function(
        name="item_detection",
        description="Vector search over the item detection index. Returns the filter to be subsequently used in search_products function call.",
    )
    async def item_detection(
        self,
        query: Annotated[str, "Entity extraction query for item detection"],
    ) -> dict:
        query = (query or "").strip()
        if not query:
            return SearchResponse(results=[], facets=None, total_count=0)

        print(f"Running item detection search with query: {query}")

        results = await search_by_text_vector(
            self._item_detection_client,
            text=query,
            vector_fields=self._settings.vector_fields_item_detection.combined_metadata_vector,
            select=self._settings.select_fields_item_detection,
            top=1,
        )

        filter = {
            "ProductGroupName": results.results[0].document.get("ProductGroupName"),
            "ProductName": results.results[0].document.get("ProductName"),
            "IndexName": results.results[0].document.get("IndexName"),
            "ProductTypeName": results.results[0].document.get("ProductTypeName"),
            "SectionName": results.results[0].document.get("SectionName"),
            "DepartmentName": results.results[0].document.get("DepartmentName"),
            "IndexGroupName": results.results[0].document.get("IndexGroupName"),
            "GarmentGroupName": results.results[0].document.get("GarmentGroupName"),
        }
        filter_string = " and ".join(
            [
                f"{key} eq '{value}'"
                for key, value in filter.items()
                if value and key in self._settings.item_detection_filter_fields
            ]
        )
        return filter_string
