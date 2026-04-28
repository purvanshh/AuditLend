from dataclasses import FrozenInstanceError

import pytest

from engine.rule_sets import ACTIVE_RULE_SET, ALL_RULE_SETS, RULE_SET_V1


def test_rule_set_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        RULE_SET_V1.credit_weight = 50


def test_changing_weights_requires_new_version() -> None:
    active = ACTIVE_RULE_SET

    assert active.version in ALL_RULE_SETS
    assert active.version == "RULE_SET_V1"
    assert active.to_dict()["weights"] == {
        "credit": 40.0,
        "stability": 20.0,
        "dti": 25.0,
        "gst": 15.0,
    }


def test_all_rule_sets_have_unique_versions() -> None:
    versions = [rule_set.version for rule_set in ALL_RULE_SETS.values()]

    assert len(versions) == len(set(versions))
