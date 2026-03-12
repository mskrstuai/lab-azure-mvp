import asyncio
import logging
from typing import List, Optional, Union

from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery, QueryType

from ..models.search import SearchResult, SearchResponse

logger = logging.getLogger(__name__)


async def search(
    client: SearchClient,
    *,
    search_text: Optional[str] = None,
    vectorize_text: bool = False,
    vector_fields: Optional[List[str]] = None,
    k_nearest_neighbors: int = 100,
    filter: Optional[str] = None,
    select: Optional[List[str]] = None,
    facets: Optional[List[str]] = None,
    top: int = 30,
    semantic_configuration_name: Optional[str] = None,
) -> SearchResponse:
    """
    Async search operation for Azure AI Search.

    Supports three modes:
    1. Text-only: Just search_text provided (vectorize_text=False)
    2. Hybrid + semantic: vectorize_text=True (auto-vectorizes query, uses semantic reranker)
    3. Filter-only: Just filter provided, search_text defaults to "*"
    """
    query_text = search_text.strip() if search_text else search_text

    search_kwargs = {
        "search_text": query_text,
        "filter": filter,
        "top": top,
    }

    if select:
        search_kwargs["select"] = select

    if facets:
        search_kwargs["facets"] = facets

    if vectorize_text:
        if not vector_fields:
            raise ValueError("vector_fields required when using vector search")
        if not semantic_configuration_name:
            raise ValueError(
                "semantic_configuration_name required for hybrid/vector search"
            )

        search_kwargs["vector_queries"] = [
            VectorizableTextQuery(
                text=query_text,
                k_nearest_neighbors=k_nearest_neighbors,
                fields=",".join(vector_fields),
            )
        ]
        search_kwargs["query_type"] = QueryType.SEMANTIC
        search_kwargs["semantic_configuration_name"] = semantic_configuration_name

    results_iterator = await asyncio.to_thread(client.search, **search_kwargs)

    search_results: List[SearchResult] = []
    for doc in results_iterator:
        d = dict(doc)

        search_score = d.pop("@search.score", None)
        reranker_score = d.pop("@search.reranker_score", None)
        captions = d.pop("@search.captions", None)

        for key in list(d.keys()):
            if key.startswith("@search."):
                d.pop(key, None)

        search_results.append(
            SearchResult(
                document=d,
                search_score=search_score,
                reranker_score=reranker_score,
                captions=captions,
            )
        )

    response_facets = results_iterator.get_facets() if facets else None

    return SearchResponse(
        results=search_results,
        facets=response_facets,
        total_count=len(search_results),
    )


async def search_by_filter(
    client: SearchClient,
    *,
    filter: str,
    select: Optional[List[str]] = None,
    top: int = 1,
) -> SearchResponse:
    """Simple filter-based search (no text, no vector)."""
    return await search(
        client,
        search_text="*",
        filter=filter,
        select=select,
        top=top,
    )


async def search_by_vector(
    client: SearchClient,
    *,
    vector: List[float],
    vector_field: str,
    k_nearest_neighbors: int = 50,
    filter: Optional[str] = None,
    select: Optional[List[str]] = None,
    top: int = 10,
) -> SearchResponse:
    """Vector-only search using a pre-computed embedding."""
    from azure.search.documents.models import VectorizedQuery

    search_kwargs = {
        "search_text": "*",
        "filter": filter,
        "top": top,
        "vector_queries": [
            VectorizedQuery(
                vector=vector,
                k_nearest_neighbors=k_nearest_neighbors,
                fields=vector_field,
            )
        ],
    }

    if select:
        search_kwargs["select"] = select

    results_iterator = await asyncio.to_thread(client.search, **search_kwargs)

    search_results: List[SearchResult] = []
    for doc in results_iterator:
        d = dict(doc)
        search_score = d.pop("@search.score", None)
        reranker_score = d.pop("@search.reranker_score", None)
        captions = d.pop("@search.captions", None)

        for key in list(d.keys()):
            if key.startswith("@search."):
                d.pop(key, None)

        search_results.append(
            SearchResult(
                document=d,
                search_score=search_score,
                reranker_score=reranker_score,
                captions=captions,
            )
        )

    return SearchResponse(
        results=search_results,
        facets=None,
        total_count=len(search_results),
    )


async def search_by_text_vector(
    client: SearchClient,
    *,
    text: str,
    vector_fields: Union[str, List[str]],
    k_nearest_neighbors: int = 50,
    filter: Optional[str] = None,
    select: Optional[List[str]] = None,
    top: int = 10,
) -> SearchResponse:
    """Vector-only search using a text query (auto-vectorized by Azure AI Search)."""
    fields_str = vector_fields if isinstance(vector_fields, str) else ",".join(vector_fields)

    search_kwargs = {
        "search_text": text,
        "filter": filter,
        "top": top,
        "vector_queries": [
            VectorizableTextQuery(
                text=text,
                k_nearest_neighbors=k_nearest_neighbors,
                fields=fields_str,
            )
        ],
    }

    if select:
        search_kwargs["select"] = select

    results_iterator = await asyncio.to_thread(client.search, **search_kwargs)

    search_results: List[SearchResult] = []
    for doc in results_iterator:
        d = dict(doc)
        search_score = d.pop("@search.score", None)
        reranker_score = d.pop("@search.reranker_score", None)
        captions = d.pop("@search.captions", None)

        for key in list(d.keys()):
            if key.startswith("@search."):
                d.pop(key, None)

        search_results.append(
            SearchResult(
                document=d,
                search_score=search_score,
                reranker_score=reranker_score,
                captions=captions,
            )
        )

    return SearchResponse(
        results=search_results,
        facets=None,
        total_count=len(search_results),
    )
