from dataclasses import dataclass


@dataclass(frozen=True)
class RuleSet:
    version: str
    description: str
    created_at: str
    credit_weight: float
    stability_weight: float
    dti_weight: float
    gst_weight: float
    data_quality_penalty: float
    max_data_quality_penalty: float
    approve_high_threshold: float
    approve_moderate_threshold: float
    decline_threshold: float
    moderate_max_dti: float
    decline_dti_threshold: float

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "description": self.description,
            "created_at": self.created_at,
            "weights": {
                "credit": self.credit_weight,
                "stability": self.stability_weight,
                "dti": self.dti_weight,
                "gst": self.gst_weight,
            },
            "data_quality": {
                "penalty": self.data_quality_penalty,
                "max_penalty": self.max_data_quality_penalty,
            },
            "thresholds": {
                "approve_high": self.approve_high_threshold,
                "approve_moderate": self.approve_moderate_threshold,
                "decline": self.decline_threshold,
                "moderate_max_dti": self.moderate_max_dti,
                "decline_dti": self.decline_dti_threshold,
            },
        }


RULE_SET_V1 = RuleSet(
    version="RULE_SET_V1",
    description="Initial conservative scorecard. SME-derived weights; empirical validation pending.",
    created_at="2025-01-15",
    credit_weight=40.0,
    stability_weight=20.0,
    dti_weight=25.0,
    gst_weight=15.0,
    data_quality_penalty=5.0,
    max_data_quality_penalty=15.0,
    approve_high_threshold=70.0,
    approve_moderate_threshold=55.0,
    decline_threshold=35.0,
    moderate_max_dti=0.5,
    decline_dti_threshold=0.6,
)

ACTIVE_RULE_SET = RULE_SET_V1

ALL_RULE_SETS = {rule_set.version: rule_set for rule_set in [RULE_SET_V1]}
