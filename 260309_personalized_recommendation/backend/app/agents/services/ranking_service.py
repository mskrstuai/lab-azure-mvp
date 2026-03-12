"""
Ranking Service

Handles reranking of search results using recommender system scores.
"""

import logging
import os
from typing import List, Dict, Optional

import pandas as pd
from azure.identity import DefaultAzureCredential

from ..models.search import SearchResult, SearchResponse, ItemsSelectFields
from ..models.const import RankingModel, NormalizationMethod
from ..settings.ranking_settings import RankingSettings
from ..settings.data_settings import DataSettings

logger = logging.getLogger(__name__)


class RankingService:
    """
    Service for reranking search results using recommender system scores.
    """

    _two_stage_df: Optional[pd.DataFrame] = None
    _als_cf_df: Optional[pd.DataFrame] = None
    _data_settings: Optional[DataSettings] = None

    def __init__(
        self,
        user_id: str,
        config: Optional[RankingSettings] = None,
    ):
        self.user_id = user_id
        self.config = config or RankingSettings()

        if RankingService._data_settings is None:
            RankingService._data_settings = DataSettings()

    @classmethod
    def _get_storage_options(cls) -> Optional[Dict]:
        if not cls._data_settings or not cls._data_settings.storage_account_name:
            return None

        return {
            "account_name": cls._data_settings.storage_account_name,
            "credential": DefaultAzureCredential(),
        }

    @classmethod
    def _read_recommender_parquet(cls, file_name: str) -> pd.DataFrame:
        if cls._data_settings is None:
            cls._data_settings = DataSettings()

        recommender_path = cls._data_settings.recommender_models_path
        local_path = os.path.join(recommender_path, file_name)

        if os.path.isfile(local_path):
            logger.info(f"Loading from local path: {local_path}")
            return pd.read_parquet(local_path)

        if cls._data_settings.storage_account_name:
            container = cls._data_settings.recommender_models_container
            abfs_path = f"abfs://{container}/{file_name}"
            logger.info(f"Loading from Azure Blob: {abfs_path}")
            return pd.read_parquet(
                abfs_path,
                storage_options=cls._get_storage_options(),
            )

        raise FileNotFoundError(
            f"Recommender model file not found: {local_path}. "
            "Either place the file locally, or set DATA_STORAGE_ACCOUNT_NAME and "
            "DATA_RECOMMENDER_MODELS_CONTAINER for Azure Blob (uses Azure AD auth)."
        )

    @classmethod
    def _load_two_stage(cls) -> pd.DataFrame:
        if cls._two_stage_df is not None:
            return cls._two_stage_df

        if cls._data_settings is None:
            cls._data_settings = DataSettings()

        file_name = cls._data_settings.two_stage_top100_file
        logger.info(f"Loading two-stage top100: {file_name}")
        cls._two_stage_df = cls._read_recommender_parquet(file_name)
        cls._two_stage_df["article_id"] = cls._two_stage_df["article_id"].astype(str)
        logger.info(f"Loaded {len(cls._two_stage_df)} rows from two-stage model")

        return cls._two_stage_df

    @classmethod
    def _load_als_cf(cls) -> pd.DataFrame:
        if cls._als_cf_df is not None:
            return cls._als_cf_df

        if cls._data_settings is None:
            cls._data_settings = DataSettings()

        file_name = cls._data_settings.als_cf_model_file
        logger.info(f"Loading ALS CF model: {file_name}")
        cls._als_cf_df = cls._read_recommender_parquet(file_name)
        logger.info(f"Loaded {len(cls._als_cf_df)} rows from ALS CF model")
        cls._als_cf_df.rename(columns={"als_score": "score"}, inplace=True)
        cls._als_cf_df["article_id"] = cls._als_cf_df["article_id"].astype(str)

        return cls._als_cf_df

    def _get_candidate_ids(self) -> List[str]:
        try:
            df = self._load_two_stage()
            customer_df = df[df["customer_id"] == self.user_id]

            if customer_df.empty:
                logger.warning(f"Customer {self.user_id} not found in two-stage model")
                return []

            return customer_df.sort_values("score", ascending=False)[
                "article_id"
            ].tolist()
        except Exception as e:
            logger.warning(f"Failed to get RS candidates for {self.user_id}: {e}")
            return []

    def get_candidate_filter(self) -> Optional[str]:
        candidate_ids = self._get_candidate_ids()
        if not candidate_ids:
            logger.warning("No RS candidates available")
            return None

        ids_str = ",".join(candidate_ids)
        logger.info(f"Built RS candidate filter with {len(candidate_ids)} items")
        return f"search.in({ItemsSelectFields().id}, '{ids_str}', ',')"

    def _get_rs_scores(
        self,
        article_ids: List[str],
        model: RankingModel,
    ) -> Dict[str, Optional[float]]:
        if model == RankingModel.TWO_STAGE:
            df = self._load_two_stage()
        else:
            df = self._load_als_cf()

        customer_df = df[df["customer_id"] == self.user_id]

        if customer_df.empty:
            logger.warning(f"Customer {self.user_id} not found in {model} model")
            return {aid: None for aid in article_ids}

        scores_df = customer_df[customer_df["article_id"].isin(article_ids)]
        score_map = dict(zip(scores_df["article_id"], scores_df["score"]))

        return {aid: score_map.get(aid) for aid in article_ids}

    def _normalize_min_max(self, scores: List[float]) -> List[float]:
        if not scores:
            return []

        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            return [0.5] * len(scores)

        return [(s - min_score) / (max_score - min_score) for s in scores]

    def _normalize_sigmoid_zscore(self, scores: List[float]) -> List[float]:
        import math

        if not scores:
            return []

        n = len(scores)
        if n == 1:
            return [0.5]

        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance) if variance > 0 else 1.0

        if std == 0:
            return [0.5] * n

        normalized = []
        for s in scores:
            z = (s - mean) / std
            sigmoid = 1.0 / (1.0 + math.exp(-z))
            normalized.append(sigmoid)

        return normalized

    def _normalize_scores(self, scores: List[float]) -> List[float]:
        if self.config.normalization_method == NormalizationMethod.SIGMOID_ZSCORE:
            return self._normalize_sigmoid_zscore(scores)
        else:
            return self._normalize_min_max(scores)

    def _compute_final_score(
        self,
        search_score_normalized: float,
        rs_score_normalized: Optional[float],
        apply_rs_rerank: bool,
    ) -> float:
        if not apply_rs_rerank or rs_score_normalized is None:
            return search_score_normalized

        return (
            self.config.search_weight * search_score_normalized
            + self.config.rs_weight * rs_score_normalized
        )

    def rerank_results(
        self,
        results: List[SearchResult],
        model: RankingModel = RankingModel.ALS_CF,
        apply_rs_rerank: bool = True,
    ) -> List[SearchResult]:
        if not results:
            return []

        if model == RankingModel.TWO_STAGE:
            apply_rs_rerank = self.config.two_stage_apply_rs_rerank

        article_ids = [r.article_id for r in results if r.article_id]
        search_scores = [r.effective_search_score for r in results]

        rs_scores = self._get_rs_scores(article_ids, model)

        normalized_search = self._normalize_scores(search_scores)

        valid_rs_items = [(aid, s) for aid, s in rs_scores.items() if s is not None]
        if valid_rs_items:
            valid_ids, valid_scores = zip(*valid_rs_items)
            normalized_valid = self._normalize_scores(list(valid_scores))
            normalized_rs_map = dict(zip(valid_ids, normalized_valid))
        else:
            normalized_rs_map = {}

        search_rank_order = sorted(
            range(len(results)),
            key=lambda i: results[i].effective_search_score,
            reverse=True,
        )
        search_rank_map = {idx: rank + 1 for rank, idx in enumerate(search_rank_order)}

        valid_rs_scores = [s for s in rs_scores.values() if s is not None]
        min_rs_score = min(valid_rs_scores) - 1 if valid_rs_scores else -1

        rs_rank_map = {}
        items_for_rs_ranking = [
            (
                i,
                (
                    rs_scores.get(results[i].article_id)
                    if rs_scores.get(results[i].article_id) is not None
                    else min_rs_score
                ),
            )
            for i in range(len(results))
            if results[i].article_id
        ]
        if items_for_rs_ranking:
            items_for_rs_ranking.sort(key=lambda x: x[1], reverse=True)
            for rank, (idx, _) in enumerate(items_for_rs_ranking):
                rs_rank_map[idx] = rank + 1

        reranked_results = []
        for i, result in enumerate(results):
            article_id = result.article_id
            raw_rs_score = rs_scores.get(article_id) if article_id else None
            normalized_rs = normalized_rs_map.get(article_id) if article_id else None

            final_score = self._compute_final_score(
                normalized_search[i],
                normalized_rs,
                apply_rs_rerank,
            )

            reranked_result: SearchResult = result.model_copy(
                update={
                    "rs_score": raw_rs_score,
                    "rs_model": model if raw_rs_score is not None else None,
                    "final_score": final_score,
                    "search_rank": search_rank_map[i],
                    "rs_rank": rs_rank_map.get(i),
                }
            )
            reranked_results.append(reranked_result)

        reranked_results.sort(key=lambda r: r.final_score or 0, reverse=True)

        for i, result in enumerate(reranked_results):
            result.final_rank = i + 1

        logger.debug(
            f"Reranked {len(reranked_results)} results using {model}, "
            f"{len(valid_rs_items)} had RS scores"
        )

        return reranked_results

    def rerank_response(
        self,
        response: SearchResponse,
        model: RankingModel = RankingModel.ALS_CF,
        apply_rs_rerank: bool = True,
    ) -> SearchResponse:
        reranked_results = self.rerank_results(
            response.results, model=model, apply_rs_rerank=apply_rs_rerank
        )

        return SearchResponse(
            results=reranked_results,
            facets=response.facets,
            total_count=response.total_count,
            is_reranked=True,
            reranking_model=model,
        )

    @classmethod
    def clear_cache(cls) -> None:
        cls._two_stage_df = None
        cls._als_cf_df = None
        logger.info("Ranking service cache cleared")
