from enum import Enum


class PreferencesType(Enum):
    OVERALL = "overall"
    CATEGORY = "category"
    SHORT_TERM = "short_term"


class AggregationType(Enum):
    HIERARCHY = "hierarchy"
    RECURRENT = "recurrent"


class RankingModel(Enum):
    TWO_STAGE = "two_stage"
    ALS_CF = "als_cf"


class NormalizationMethod(Enum):
    MIN_MAX = "min_max"
    SIGMOID_ZSCORE = "sigmoid_zscore"
