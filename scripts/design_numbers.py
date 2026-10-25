"""Print the numbers DESIGN.md cites, computed from the seed data.

    python scripts/design_numbers.py

Memberships stand in for "who joins what". For each member with interests and
each Circle, the pair is labeled by how they match, then we compare how often
the member belongs to the Circle. A lift near 1x means the match tells us
nothing about membership. The industry check compares pairs of members instead.

The four scenario users (7, 15, 23, 42) are left out of the membership
comparisons, because their memberships were placed by hand for the assignment.
"""

import random
import sys
import tempfile
from collections import Counter, defaultdict
from itertools import combinations, pairwise
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.recommender import days_since  # noqa: E402

SCENARIO_USERS = {7, 15, 23, 42}
RESAMPLES = 2000


def match_kind(interests, topic, tags):
    if topic in interests:
        return "topic"
    if (set(tags) - {topic}) & interests:
        return "tag only"
    return "none"


def main():
    with tempfile.TemporaryDirectory() as tmp, db.connect(db.build_database(Path(tmp) / "circles.db")) as conn:
        snapshot = db.load_snapshot(conn)
        circles = conn.execute("SELECT id, topic_slug, format, member_count FROM circles").fetchall()
        tags = defaultdict(list)
        for r in conn.execute("SELECT circle_id, topic_slug FROM circle_tags"):
            tags[r["circle_id"]].append(r["topic_slug"])
        interests = defaultdict(set)
        for r in conn.execute("SELECT user_id, topic_slug FROM user_interests"):
            interests[r["user_id"]].add(r["topic_slug"])
        member_of = defaultdict(set)
        for r in conn.execute("SELECT user_id, circle_id FROM memberships"):
            member_of[r["user_id"]].add(r["circle_id"])
        users = [r["id"] for r in conn.execute("SELECT id FROM users ORDER BY id")]
        locations = [r["location"] for r in conn.execute("SELECT location FROM users")]
        industry = {r["id"]: r["industry"] for r in conn.execute("SELECT id, industry FROM users")}
        distinct_bodies = conn.execute("SELECT COUNT(DISTINCT body) FROM posts").fetchone()[0]
        total_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]

    # 1. Topic and tag matches vs membership.
    people = [u for u in users if u not in SCENARIO_USERS and interests[u]]
    counts = {u: defaultdict(lambda: [0, 0]) for u in people}   # user -> kind -> [pairs, memberships]
    for u in people:
        for c in circles:
            kind = match_kind(interests[u], c["topic_slug"], tags[c["id"]])
            counts[u][kind][0] += 1
            counts[u][kind][1] += c["id"] in member_of[u]

    def lifts(sample):
        total = defaultdict(lambda: [0, 0])
        for u in sample:
            for kind, (pairs, members) in counts[u].items():
                total[kind][0] += pairs
                total[kind][1] += members
        rate = {kind: members / pairs for kind, (pairs, members) in total.items()}
        return rate, {kind: rate[kind] / rate["none"] for kind in rate}

    rate, lift = lifts(people)
    rng = random.Random(0)
    resampled = [lifts([rng.choice(people) for _ in people])[1] for _ in range(RESAMPLES)]
    print(f"Membership by match type ({len(people)} members with interests):")
    for kind in ("topic", "tag only", "none"):
        values = sorted(r[kind] for r in resampled)
        low, high = values[int(0.05 * RESAMPLES)], values[int(0.95 * RESAMPLES)]
        print(f"  {kind:<9} {rate[kind]:6.1%}   lift {lift[kind]:.2f}x   90% range {low:.2f}x to {high:.2f}x")

    # 2. Format vs membership. In-person Circles happen to be bigger, which is the whole gap.
    by_format = defaultdict(lambda: [0, 0])
    for u in users:
        if u in SCENARIO_USERS:
            continue
        for c in circles:
            key = "in person" if c["format"] == "in_person" else "online or hybrid"
            by_format[key][0] += 1
            by_format[key][1] += c["id"] in member_of[u]
    in_rate = by_format["in person"][1] / by_format["in person"][0]
    on_rate = by_format["online or hybrid"][1] / by_format["online or hybrid"][0]
    in_size = mean(c["member_count"] for c in circles if c["format"] == "in_person")
    on_size = mean(c["member_count"] for c in circles if c["format"] != "in_person")
    print(f"\nFormat: in-person membership rate is {in_rate / on_rate:.2f}x online or hybrid,")
    print(f"  but in-person Circles average {in_size:.1f} members vs {on_size:.1f}, which explains the gap.")

    # 3. Chance an in-person Circle is in her city, if Circles were spread across
    #    cities the way members are: the sum of each city's share, squared.
    cities = Counter(loc for loc in locations if loc and loc != "Remote")
    total = sum(cities.values())
    same_city = sum((n / total) ** 2 for n in cities.values())
    print(f"\nSame-city chance for an in-person Circle we can't place: {same_city:.0%}")

    # 4. The gap in activity that makes the inactive cutoff robust.
    idle = sorted(days_since(c.last_activity_at, snapshot.taken_at) for c in snapshot.circles)
    gap = max(pairwise(idle), key=lambda pair: pair[1] - pair[0])
    print(f"\nDays since last activity: no Circle between {gap[0]:.0f} and {gap[1]:.0f} days,")
    print(f"  so any inactive cutoff from {gap[0] + 1:.0f} to {gap[1] - 1:.0f} days removes the same Circles.")

    # 5. Industry. Circles have no industry of their own, so ask whether members
    #    cluster by industry. Comparing pairs of members, not member-Circle pairs,
    #    keeps Circle size out of it: small Circles would otherwise skew the rates.
    with_industry = [u for u in users if u not in SCENARIO_USERS and industry[u]]

    def industry_pair_lift(sample):
        pairs = {True: [0, 0], False: [0, 0]}   # same industry? -> [pairs, pairs sharing a Circle]
        for u, v in combinations(sample, 2):
            if u == v:   # the same member drawn twice in a resample
                continue
            same = industry[u] == industry[v]
            pairs[same][0] += 1
            pairs[same][1] += bool(member_of[u] & member_of[v])
        return (pairs[True][1] / pairs[True][0]) / (pairs[False][1] / pairs[False][0])

    lift = industry_pair_lift(with_industry)
    values = sorted(industry_pair_lift([rng.choice(with_industry) for _ in with_industry]) for _ in range(RESAMPLES))
    low, high = values[int(0.05 * RESAMPLES)], values[int(0.95 * RESAMPLES)]
    print(f"\nIndustry: two members in the same industry are {lift:.2f}x as likely to share a Circle")
    print(f"  as two in different industries (90% range {low:.2f}x to {high:.2f}x).")

    print(f"\nPost text: {distinct_bodies} distinct post bodies across {total_posts} posts.")


if __name__ == "__main__":
    main()
