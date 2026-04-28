# Score Calibration

**Current Status:** Heuristic weights based on domain expertise.

## RULE_SET_V1 (2025-01-15)

- **Methodology:** SME-derived weights with conservative thresholds.
- **Validation:** Not yet empirically validated against historical default data.
- **Known limitation:** This is a governed scorecard, not a statistically calibrated probability-of-default model.
- **Next steps:** Backtest against historical loan performance data; tune using KS, Gini/AUC, calibration curves, and adverse-action review.

## Adding A New Rule Set

1. Create a new immutable `RuleSet` instance in `engine/rule_sets.py` with a unique version.
2. Add it to `ALL_RULE_SETS`.
3. Update `ACTIVE_RULE_SET`.
4. Update `tests/unit/test_rule_governance.py` so the expected active version changes deliberately.
5. Document methodology, validation data, approval date, and known limitations here.
