"""ML model introspection and retraining endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..data_loader import normalize_customer_id
from ..similarity_model import get_model, SimilarityAlgorithm, ModelConfig

router = APIRouter()


@router.get("/model/summary")
async def model_summary():
    model = get_model()
    return model.get_model_summary()


@router.get("/model/feature-importance")
async def feature_importance():
    model = get_model()
    features = model.get_feature_importance()
    return [
        {
            "rank": i + 1,
            "category": f.category_name,
            "frequency": f"{f.frequency:.1%}",
            "discriminative_power": round(f.discriminative_power, 4),
            "avg_similarity_contribution": round(f.avg_weight_in_similarities, 4),
        }
        for i, f in enumerate(features)
    ]


@router.get("/model/explain/{customer_a}/{customer_b}")
async def explain_similarity(customer_a: str, customer_b: str, include_ci: bool = True):
    customer_a = normalize_customer_id(customer_a)
    customer_b = normalize_customer_id(customer_b)
    model = get_model()
    result = model.explain_similarity(customer_a, customer_b)
    if not include_ci:
        result.pop("confidence_interval_95", None)
        if "explanation" in result:
            result["explanation"].pop("confidence_note", None)
    return result


@router.get("/model/compare-algorithms/{customer_id}")
async def compare_algorithms(customer_id: str, limit: int = 5):
    customer_id = normalize_customer_id(customer_id)
    model = get_model()
    return model.compare_algorithms(customer_id, limit=limit)


class RetrainRequest(BaseModel):
    algorithm: str = "jaccard"
    min_similarity_threshold: float = 0.3
    use_behavioral_weights: bool = False
    top_k_neighbors: int = 10


@router.post("/model/retrain")
async def retrain_model(request: RetrainRequest):
    model = get_model()
    try:
        algo = SimilarityAlgorithm(request.algorithm.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid algorithm. Choose from: {[a.value for a in SimilarityAlgorithm]}",
        )
    new_config = ModelConfig(
        algorithm=algo,
        min_similarity_threshold=request.min_similarity_threshold,
        use_behavioral_weights=request.use_behavioral_weights,
        top_k_neighbors=request.top_k_neighbors,
    )
    metrics = model.train(new_config)
    return {
        "status": "retrained",
        "message": f"Model retrained with {algo.value} algorithm",
        "training_metrics": metrics.to_dict(),
        "new_config": new_config.to_dict(),
    }


@router.get("/model/training-metrics")
async def training_metrics():
    model = get_model()
    if model.metrics is None:
        raise HTTPException(status_code=400, detail="Model has not been trained yet")
    return model.metrics.to_dict()


@router.get("/model/algorithms")
async def list_algorithms():
    return {
        "algorithms": [
            {
                "name": "jaccard",
                "formula": "|A ∩ B| / |A ∪ B|",
                "description": "Balanced measure of overlap. Good default choice.",
                "best_for": "General customer similarity when sizes vary",
            },
            {
                "name": "cosine",
                "formula": "A·B / (||A|| × ||B||)",
                "description": "Measures angle between vectors. Scale-invariant.",
                "best_for": "When behavioral intensity matters, not just binary categories",
            },
            {
                "name": "dice",
                "formula": "2|A ∩ B| / (|A| + |B|)",
                "description": "Emphasizes overlap more than Jaccard.",
                "best_for": "When you want to reward shared categories more",
            },
            {
                "name": "overlap",
                "formula": "|A ∩ B| / min(|A|, |B|)",
                "description": "Ignores size differences entirely.",
                "best_for": "Finding small customers similar to large ones",
            },
        ],
        "current": get_model().config.algorithm.value,
    }
