from typing import ClassVar

from semantic_kernel.kernel_pydantic import KernelBaseSettings
from ..models.const import RankingModel, NormalizationMethod


class RankingSettings(KernelBaseSettings):
    """
    Ranking settings with support for multiple runtime environments.
    """

    env_prefix: ClassVar[str] = "RANKING_"

    search_weight: float = 0.9
    rs_weight: float = 0.1
    apply_rerank: bool = True
    two_stage_apply_rs_rerank: bool = True
    default_ranking_model: RankingModel = RankingModel.ALS_CF
    normalization_method: NormalizationMethod = NormalizationMethod.SIGMOID_ZSCORE

    def __post_init__(self):
        if abs(self.search_weight + self.rs_weight - 1.0) > 0.001:
            raise ValueError("search_weight + rs_weight must equal 1.0")
