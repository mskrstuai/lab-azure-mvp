"""
Similarity Model - Classical ML Layer
=====================================
Transparent and interactive ML model for customer similarity.
Supports multiple algorithms: Jaccard, Cosine, Dice, Overlap.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class SimilarityAlgorithm(str, Enum):
    """
    An enumeration of supported similarity algorithms.

    Attributes:
        JACCARD: Jaccard similarity coefficient.
        COSINE: Cosine similarity measure.
        DICE: Dice similarity coefficient.
        OVERLAP: Overlap coefficient.

    This enum is used to specify which similarity algorithm to use in similarity computations.
    """
    JACCARD = "jaccard"
    COSINE = "cosine"
    DICE = "dice"
    OVERLAP = "overlap"


@dataclass
class ModelConfig:
    algorithm: SimilarityAlgorithm = SimilarityAlgorithm.JACCARD
    min_similarity_threshold: float = 0.3
    top_k_neighbors: int = 10
    use_behavioral_weights: bool = False
    category_weights: Optional[dict] = None
    exclude_zero_categories: bool = True

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm.value,
            "min_similarity_threshold": self.min_similarity_threshold,
            "top_k_neighbors": self.top_k_neighbors,
            "use_behavioral_weights": self.use_behavioral_weights,
            "category_weights": self.category_weights,
            "exclude_zero_categories": self.exclude_zero_categories,
        }


@dataclass
class TrainingMetrics:
    trained_at: str = ""
    training_duration_ms: float = 0.0
    num_customers: int = 0
    num_categories: int = 0
    total_pairs_computed: int = 0
    avg_similarity: float = 0.0
    median_similarity: float = 0.0
    similarity_std: float = 0.0
    pairs_above_threshold: int = 0
    sparsity_ratio: float = 0.0
    algorithm_used: str = ""
    config_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CategoryImportance:
    category_index: int
    category_name: str
    frequency: float
    discriminative_power: float
    avg_weight_in_similarities: float


class SimilarityModel:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(__file__).resolve().parent.parent / "data"
        self.config = ModelConfig()
        self.metrics: Optional[TrainingMetrics] = None
        self.similarity_matrix: Optional[np.ndarray] = None
        self.customer_ids: list[str] = []
        self.category_names: list[str] = []
        self.category_vectors: Optional[np.ndarray] = None
        self.behavioral_vectors: Optional[np.ndarray] = None
        self._is_trained = False
        self._load_data()

    def _load_data(self):
        with open(self.data_dir / "customers.json") as f:
            customers_data = json.load(f)
        with open(self.data_dir / "products.json") as f:
            products_data = json.load(f)
        customers = customers_data["customers"]
        self.customer_ids = [c["customer_id"] for c in customers]
        self.category_names = [cat["name"] for cat in products_data["categories"]]
        self.category_vectors = np.array([c["category_purchases"] for c in customers])
        self.behavioral_vectors = np.array([c["behavioral_vector"] for c in customers])

    def train(self, config: Optional[ModelConfig] = None) -> TrainingMetrics:
        if config:
            self.config = config
        start_time = datetime.now()
        n = len(self.customer_ids)
        self.similarity_matrix = np.zeros((n, n))
        all_similarities = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._compute_similarity(i, j)
                self.similarity_matrix[i, j] = sim
                self.similarity_matrix[j, i] = sim
                if sim >= self.config.min_similarity_threshold:
                    all_similarities.append(sim)
        np.fill_diagonal(self.similarity_matrix, 1.0)
        end_time = datetime.now()
        duration_ms = (end_time - start_time).total_seconds() * 1000
        total_pairs = n * (n - 1) // 2
        all_sims_array = np.array(all_similarities) if all_similarities else np.array([0])
        self.metrics = TrainingMetrics(
            trained_at=start_time.isoformat(),
            training_duration_ms=round(duration_ms, 2),
            num_customers=n,
            num_categories=len(self.category_names),
            total_pairs_computed=total_pairs,
            avg_similarity=round(float(np.mean(all_sims_array)), 4) if all_similarities else 0,
            median_similarity=round(float(np.median(all_sims_array)), 4) if all_similarities else 0,
            similarity_std=round(float(np.std(all_sims_array)), 4) if all_similarities else 0,
            pairs_above_threshold=len(all_similarities),
            sparsity_ratio=round(1 - len(all_similarities) / total_pairs, 4),
            algorithm_used=self.config.algorithm.value,
            config_hash=str(hash(json.dumps(self.config.to_dict(), sort_keys=True))),
        )
        self._is_trained = True
        return self.metrics

    def _compute_similarity(self, i: int, j: int) -> float:
        vec_i = self.category_vectors[i]
        vec_j = self.category_vectors[j]
        if self.config.use_behavioral_weights:
            weights_i = self.behavioral_vectors[i][: len(vec_i)]
            weights_j = self.behavioral_vectors[j][: len(vec_j)]
            vec_i = vec_i * weights_i
            vec_j = vec_j * weights_j
        algo_map = {
            SimilarityAlgorithm.JACCARD: self._jaccard,
            SimilarityAlgorithm.COSINE: self._cosine,
            SimilarityAlgorithm.DICE: self._dice,
            SimilarityAlgorithm.OVERLAP: self._overlap,
        }
        return algo_map.get(self.config.algorithm, self._jaccard)(vec_i, vec_j)

    def _jaccard(self, a: np.ndarray, b: np.ndarray) -> float:
        if self.config.exclude_zero_categories:
            mask = (a > 0) | (b > 0)
            a, b = a[mask], b[mask]
        if len(a) == 0:
            return 0.0
        intersection = np.sum(np.minimum(a, b))
        union = np.sum(np.maximum(a, b))
        return float(intersection / union) if union > 0 else 0.0

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def _dice(self, a: np.ndarray, b: np.ndarray) -> float:
        if self.config.exclude_zero_categories:
            mask = (a > 0) | (b > 0)
            a, b = a[mask], b[mask]
        intersection = np.sum(np.minimum(a, b))
        total = np.sum(a) + np.sum(b)
        return float(2 * intersection / total) if total > 0 else 0.0

    def _overlap(self, a: np.ndarray, b: np.ndarray) -> float:
        if self.config.exclude_zero_categories:
            mask = (a > 0) | (b > 0)
            a, b = a[mask], b[mask]
        intersection = np.sum(np.minimum(a, b))
        min_size = min(np.sum(a), np.sum(b))
        return float(intersection / min_size) if min_size > 0 else 0.0

    def get_similar_customers(
        self,
        customer_id: str,
        limit: int = 10,
        min_similarity: Optional[float] = None,
        include_confidence_interval: bool = True,
    ) -> list[dict]:
        if not self._is_trained:
            self.train()
        if customer_id not in self.customer_ids:
            return []
        idx = self.customer_ids.index(customer_id)
        threshold = min_similarity or self.config.min_similarity_threshold
        similarities = self.similarity_matrix[idx]
        sorted_indices = np.argsort(-similarities)
        results = []
        for neighbor_idx in sorted_indices:
            if neighbor_idx == idx:
                continue
            sim = similarities[neighbor_idx]
            if sim < threshold:
                break
            shared = int(
                np.sum(
                    (self.category_vectors[idx] > 0)
                    & (self.category_vectors[neighbor_idx] > 0)
                )
            )
            neighbor_id = self.customer_ids[neighbor_idx]
            result = {
                "customer_id": neighbor_id,
                "similarity": round(float(sim), 4),
                "shared_categories": shared,
                "total_categories": int(
                    np.sum(
                        (self.category_vectors[idx] > 0)
                        | (self.category_vectors[neighbor_idx] > 0)
                    )
                ),
            }
            if include_confidence_interval:
                ci = self.bootstrap_confidence_interval(customer_id, neighbor_id)
                result["confidence_interval_95"] = ci
            results.append(result)
            if len(results) >= limit:
                break
        return results

    def bootstrap_confidence_interval(
        self,
        customer_a: str,
        customer_b: str,
        n_iterations: int = 1000,
        confidence_level: float = 0.95,
    ) -> tuple[float, float]:
        if customer_a not in self.customer_ids or customer_b not in self.customer_ids:
            return (0.0, 0.0)
        idx_a = self.customer_ids.index(customer_a)
        idx_b = self.customer_ids.index(customer_b)
        vec_a = self.category_vectors[idx_a]
        vec_b = self.category_vectors[idx_b]
        n_categories = len(vec_a)
        bootstrap_scores = []
        for _ in range(n_iterations):
            indices = np.random.choice(n_categories, size=n_categories, replace=True)
            resampled_a = vec_a[indices]
            resampled_b = vec_b[indices]
            sim = self._jaccard(resampled_a, resampled_b)
            bootstrap_scores.append(sim)
        alpha = 1 - confidence_level
        lower = np.percentile(bootstrap_scores, 100 * alpha / 2)
        upper = np.percentile(bootstrap_scores, 100 * (1 - alpha / 2))
        return (round(float(lower), 4), round(float(upper), 4))

    def explain_similarity(self, customer_a: str, customer_b: str) -> dict:
        if not self._is_trained:
            self.train()
        if customer_a not in self.customer_ids or customer_b not in self.customer_ids:
            return {"error": "Customer not found"}
        idx_a = self.customer_ids.index(customer_a)
        idx_b = self.customer_ids.index(customer_b)
        vec_a = self.category_vectors[idx_a]
        vec_b = self.category_vectors[idx_b]
        shared_mask = (vec_a > 0) & (vec_b > 0)
        shared_categories = [
            self.category_names[i]
            for i in range(len(self.category_names))
            if shared_mask[i]
        ]
        only_a_mask = (vec_a > 0) & (vec_b == 0)
        only_a = [
            self.category_names[i]
            for i in range(len(self.category_names))
            if only_a_mask[i]
        ]
        only_b_mask = (vec_a == 0) & (vec_b > 0)
        only_b = [
            self.category_names[i]
            for i in range(len(self.category_names))
            if only_b_mask[i]
        ]
        similarity = float(self.similarity_matrix[idx_a, idx_b])
        ci = self.bootstrap_confidence_interval(customer_a, customer_b)
        return {
            "customer_a": customer_a,
            "customer_b": customer_b,
            "similarity_score": round(similarity, 4),
            "confidence_interval_95": ci,
            "algorithm": self.config.algorithm.value,
            "explanation": {
                "formula": self._get_algorithm_formula(),
                "shared_categories": shared_categories,
                "shared_count": len(shared_categories),
                "only_in_a": only_a,
                "only_in_b": only_b,
                "union_count": len(shared_categories) + len(only_a) + len(only_b),
                "calculation": f"{len(shared_categories)} / {len(shared_categories) + len(only_a) + len(only_b)} = {similarity:.4f}",
                "confidence_note": f"95% CI [{ci[0]}, {ci[1]}] via bootstrap (1000 resamples)",
            },
        }

    def _get_algorithm_formula(self) -> str:
        formulas = {
            SimilarityAlgorithm.JACCARD: "Jaccard: |A ∩ B| / |A ∪ B|",
            SimilarityAlgorithm.COSINE: "Cosine: A·B / (||A|| × ||B||)",
            SimilarityAlgorithm.DICE: "Dice: 2|A ∩ B| / (|A| + |B|)",
            SimilarityAlgorithm.OVERLAP: "Overlap: |A ∩ B| / min(|A|, |B|)",
        }
        return formulas.get(self.config.algorithm, "Unknown algorithm")

    def get_feature_importance(self) -> list[CategoryImportance]:
        if not self._is_trained:
            self.train()
        n_customers = len(self.customer_ids)
        importances = []
        for cat_idx, cat_name in enumerate(self.category_names):
            cat_column = self.category_vectors[:, cat_idx]
            frequency = float(np.sum(cat_column > 0)) / n_customers
            discriminative = float(np.var(cat_column))
            has_category = cat_column > 0
            if np.sum(has_category) > 1:
                sub_matrix = self.similarity_matrix[has_category][:, has_category]
                avg_sim_with = float(
                    np.mean(sub_matrix[np.triu_indices(len(sub_matrix), k=1)])
                )
            else:
                avg_sim_with = 0.0
            importances.append(
                CategoryImportance(
                    category_index=cat_idx,
                    category_name=cat_name,
                    frequency=round(frequency, 4),
                    discriminative_power=round(discriminative, 4),
                    avg_weight_in_similarities=round(avg_sim_with, 4),
                )
            )
        importances.sort(key=lambda x: x.discriminative_power, reverse=True)
        return importances

    def get_model_summary(self) -> dict:
        if not self._is_trained:
            self.train()
        top_features = self.get_feature_importance()[:5]
        return {
            "model_status": "trained" if self._is_trained else "untrained",
            "current_config": self.config.to_dict(),
            "available_algorithms": [a.value for a in SimilarityAlgorithm],
            "training_metrics": self.metrics.to_dict() if self.metrics else None,
            "top_5_important_features": [
                {
                    "category": f.category_name,
                    "frequency": f"{f.frequency:.1%}",
                    "discriminative_power": f.discriminative_power,
                }
                for f in top_features
            ],
            "tunable_parameters": {
                "algorithm": "Similarity algorithm (jaccard, cosine, dice, overlap)",
                "min_similarity_threshold": "Minimum score to consider customers similar (0.0-1.0)",
                "top_k_neighbors": "Number of neighbors to compute per customer",
                "use_behavioral_weights": "Weight categories by behavioral intensity vectors",
                "exclude_zero_categories": "Ignore categories neither customer purchases",
            },
        }

    def compare_algorithms(self, customer_id: str, limit: int = 5) -> dict:
        if customer_id not in self.customer_ids:
            return {"error": f"Customer {customer_id} not found"}
        results = {}
        original_algo = self.config.algorithm
        for algo in SimilarityAlgorithm:
            self.config.algorithm = algo
            self.train()
            neighbors = self.get_similar_customers(customer_id, limit=limit)
            results[algo.value] = {
                "neighbors": neighbors,
                "formula": self._get_algorithm_formula(),
            }
        self.config.algorithm = original_algo
        self.train()
        return {
            "customer_id": customer_id,
            "comparison": results,
            "insight": "Different algorithms weight shared vs unique categories differently.",
        }


_model_instance: Optional[SimilarityModel] = None


def get_model() -> SimilarityModel:
    global _model_instance
    if _model_instance is None:
        _model_instance = SimilarityModel()
        _model_instance.train()
    return _model_instance


def reset_model():
    global _model_instance
    _model_instance = None
