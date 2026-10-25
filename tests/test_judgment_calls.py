"""Each judgment call in DESIGN.md, varied on its own across the range given there.

The four scenarios must pass at every value, so none of them depends on a tuned
number, and the Circles on members' own topics must barely move.
"""

from dataclasses import replace

import pytest
import test_recommender as scenarios

from app import recommender
from app.recommender import enough_levels, recommend

SCENARIOS = [
    scenarios.test_cold_start_user_42_gets_lively_circles_across_topics,
    scenarios.test_obvious_matches_user_7_gets_circles_5_and_6_first,
    scenarios.test_duplicates_user_15_gets_only_one_of_three_negotiation_circles,
    scenarios.test_full_and_inactive_user_23_gets_the_healthy_alternative,
]

VALUES = {
    "MAX_IDLE_DAYS": [21, 30, 60, 90, 150, 226],
    "RECENCY_HALF_LIFE_DAYS": [1, 7.5, 15, 30, 60, 365],
    "ENOUGH_PERCENTILE": [1, 25, 50, 75, 90, 99],
    "COMMENT_WEIGHT": [0, 1, 2, 5, 30, 100],
}


def ids(recs):
    return [rec.circle.id for rec in recs]


def topic_picks(recs):
    return {rec.circle.id for rec in recs if rec.topic_match}


@pytest.fixture(scope="module")
def shipped(member, snapshot, all_user_ids):
    """Every member's list with the settings as shipped."""
    return {u: recommend(member(u), snapshot) for u in all_user_ids}


@pytest.mark.parametrize("setting, value", [(s, v) for s, values in VALUES.items() for v in values], ids=str)
def test_scenarios_hold_across_each_judgment_call(setting, value, member, snapshot, shipped, monkeypatch):
    monkeypatch.setattr(recommender, setting, value)
    # The snapshot computed its "enough" levels at load time, and two of these
    # settings feed them, so recompute.
    varied = replace(snapshot, enough=enough_levels(snapshot.circles))

    for check in SCENARIOS:
        check(member, varied)
    moved = [u for u, recs in shipped.items() if topic_picks(recommend(member(u), varied)) != topic_picks(recs)]
    assert len(moved) <= 1, moved


@pytest.mark.parametrize("days", [21, 226])
def test_inactive_cutoffs_from_21_to_226_days_give_identical_lists(days, member, snapshot, shipped, monkeypatch):
    # No Circle was last active between 20 and 227 days ago. A shorter cutoff
    # can only remove more Circles, so equal lists at both ends mean equal lists
    # for every cutoff in between.
    monkeypatch.setattr(recommender, "MAX_IDLE_DAYS", days)
    after = {u: ids(recommend(member(u), snapshot)) for u in shipped}
    assert after == {u: ids(recs) for u, recs in shipped.items()}
