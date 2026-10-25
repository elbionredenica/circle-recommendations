"""The four scenarios from the assignment, plus rules that must hold for every member."""

from app.recommender import ineligibility_reason, recommend


def ids(recs):
    return [rec.circle.id for rec in recs]


# --- Scenarios ---------------------------------------------------------------

def test_cold_start_user_42_gets_lively_circles_across_topics(member, snapshot):
    recs = recommend(member(42), snapshot)

    assert len(recs) == 5
    assert len({rec.circle.topic for rec in recs}) == 5            # five different topics
    assert not any(rec.topic_match for rec in recs)                # no interests to match
    assert all(rec.can_surely_attend for rec in recs)              # nothing we can't confirm she can attend


def test_obvious_matches_user_7_gets_circles_5_and_6_first(member, snapshot):
    # Interests: leadership-skills, public-speaking.
    assert set(ids(recommend(member(7), snapshot))[:2]) == {5, 6}


def test_duplicates_user_15_gets_only_one_of_three_negotiation_circles(member, snapshot):
    # Circles 10, 11 and 12 are near-identical negotiation Circles.
    recommended = set(ids(recommend(member(15), snapshot)))
    assert len(recommended & {10, 11, 12}) == 1


def test_full_and_inactive_user_23_gets_the_healthy_alternative(member, snapshot):
    # Circle 20 is full and 21 is inactive. Circle 22 is the healthy alternative.
    recommended = ids(recommend(member(23), snapshot))
    assert recommended[0] == 22
    assert 20 not in recommended
    assert 21 not in recommended


# --- Rules for every member ----------------------------------------------------

def test_only_joinable_live_circles_are_recommended(member, snapshot, all_user_ids):
    for user_id in all_user_ids:
        m = member(user_id)
        for rec in recommend(m, snapshot):
            assert ineligibility_reason(m, rec.circle, snapshot.taken_at) is None, (user_id, rec.circle.id)


def test_topic_matches_come_before_everything_else(member, snapshot, all_user_ids):
    for user_id in all_user_ids:
        flags = [rec.topic_match for rec in recommend(member(user_id), snapshot)]
        assert flags == sorted(flags, reverse=True), user_id


def test_no_topic_repeats_while_other_topics_are_available(member, snapshot, all_user_ids):
    for user_id in all_user_ids:
        topics = [rec.circle.topic or f"untagged:{rec.circle.id}" for rec in recommend(member(user_id), snapshot)]
        assert len(set(topics)) == len(topics), user_id


def test_every_pick_has_three_reasons(member, snapshot, all_user_ids):
    for user_id in all_user_ids:
        for rec in recommend(member(user_id), snapshot):
            assert len(rec.reasons) == 3 and all(rec.reasons), (user_id, rec.circle.id)


def test_limit_is_respected(member, snapshot):
    assert len(recommend(member(7), snapshot, limit=1)) == 1
    assert len(recommend(member(7), snapshot, limit=10)) == 10


def test_results_are_deterministic(member, snapshot):
    assert ids(recommend(member(15), snapshot)) == ids(recommend(member(15), snapshot))
