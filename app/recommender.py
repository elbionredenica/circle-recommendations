"""Rank Circles for one member.

The ranking runs in four steps:

1. Filter out Circles she can't or shouldn't join.
2. Sort the rest by three keys, compared in order: Circles on one of her
   topics first, then Circles she can surely attend, then health.
3. Keep the best Circle per topic, so near-duplicate Circles don't crowd
   the list.
4. Explain each pick in short sentences built from the facts that ranked it.

Everything in this module is pure. It takes plain objects and returns plain
objects, so it can be tested without a database. DESIGN.md explains the
reasoning behind each rule and number.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

# Circles meet about once a month. A Circle quiet for one and a half meeting
# cycles is treated as inactive and never recommended.
MAX_IDLE_DAYS = 45

# Recency credit halves every 15 quiet days (half a monthly cycle), so a
# Circle at the 45-day cutoff keeps one eighth of it.
RECENCY_HALF_LIFE_DAYS = 15

# "Enough" activity is the level the busiest quarter of Circles reach. Past it,
# more activity earns no extra credit, so the busiest Circles can't take every
# slot. At the median, half of all Circles would get full credit and health
# couldn't separate them. At the max, one outlier would set the bar.
ENOUGH_PERCENTILE = 75

# In engagement, a comment (a member answering a member) counts double a
# reaction or a save. A reply takes more effort than a tap, and 2 is the
# smallest step up.
COMMENT_WEIGHT = 2

# Each Circle is a monthly commitment, so a short list is easier to choose from.
DEFAULT_LIMIT = 5

FORMAT_PHRASES = {
    "virtual": "Meets online",
    "hybrid": "Meets in person and online",
    "in_person": "Meets in person",
}


@dataclass(frozen=True)
class Circle:
    id: int
    name: str
    topic: str | None              # topic slug, None for Circles without one
    format: str                    # "in_person" | "virtual" | "hybrid"
    access: str                    # "public" | "unlisted"
    join_policy: str               # "open" | "request"
    max_members: int | None        # None means uncapped
    member_count: int
    last_activity_at: datetime
    feed_posts_30d: int
    chat_messages_30d: int
    # Engagement on feed posts from the last 30 days, summed per Circle.
    recent_posts: int
    recent_reactions: int
    recent_comments: int
    recent_saves: int


@dataclass(frozen=True)
class Member:
    id: int
    interests: frozenset[str]      # topic slugs she chose, may be empty
    circle_ids: frozenset[int]     # Circles she already belongs to


@dataclass(frozen=True)
class EnoughLevels:
    """How much of each activity signal counts as 'enough' for full credit."""
    posts: int
    chat: int
    engagement: int


@dataclass(frozen=True)
class Snapshot:
    """Everything the ranker needs about the Circles, as of one moment."""
    taken_at: datetime             # "now" for every time calculation
    circles: tuple[Circle, ...]
    topic_labels: dict[str, str]   # slug -> display label
    enough: EnoughLevels


@dataclass(frozen=True)
class Recommendation:
    circle: Circle
    topic_match: bool
    can_surely_attend: bool
    health: float
    reasons: tuple[str, ...] = ()


# --- Signals --------------------------------------------------------------

def days_since(moment: datetime, now: datetime) -> float:
    """Fractional days between two timestamps."""
    return (now - moment).total_seconds() / 86_400


def engagement_per_post(circle: Circle) -> float:
    """Average of reactions + 2 x comments + saves over the last 30 days' posts."""
    if circle.recent_posts == 0:
        return 0.0
    weighted = circle.recent_reactions + COMMENT_WEIGHT * circle.recent_comments + circle.recent_saves
    return weighted / circle.recent_posts


def enough_levels(circles: Sequence[Circle]) -> EnoughLevels:
    """The 75th percentile of each activity signal across all Circles."""

    def percentile(values: list[float]) -> int:
        cut_points = statistics.quantiles(values, n=100, method="inclusive")
        # Rounded to a whole number, and at least 1 so a quiet snapshot can't
        # divide by zero later.
        return max(1, round(cut_points[ENOUGH_PERCENTILE - 1]))

    return EnoughLevels(
        posts=percentile([c.feed_posts_30d for c in circles]),
        chat=percentile([c.chat_messages_30d for c in circles]),
        engagement=percentile([engagement_per_post(c) for c in circles]),
    )


def health(circle: Circle, snapshot: Snapshot) -> float:
    """How alive a Circle is, from 0 to 1.

    The plain average of four credits, each from 0 to 1. Three count activity up
    to the 'enough' level. The fourth decays with time since the last activity.
    The weights are equal because there's no outcome data (who joined and
    stayed) to fit them against.
    """
    enough = snapshot.enough
    idle_days = days_since(circle.last_activity_at, snapshot.taken_at)
    credits = (
        min(1.0, circle.feed_posts_30d / enough.posts),
        min(1.0, circle.chat_messages_30d / enough.chat),
        0.5 ** (idle_days / RECENCY_HALF_LIFE_DAYS),
        min(1.0, engagement_per_post(circle) / enough.engagement),
    )
    return sum(credits) / len(credits)


def can_surely_attend(circle: Circle) -> bool:
    """Online and hybrid Circles can be joined from anywhere.

    In-person Circles have no location in the data, so we can't confirm she can
    attend one. They rank after Circles she surely can. With Circle locations,
    this would compare metro areas instead.
    """
    return circle.format != "in_person"


# --- Step 1: filter --------------------------------------------------------

def is_full(circle: Circle) -> bool:
    return circle.max_members is not None and circle.member_count >= circle.max_members


def seats_left(circle: Circle) -> int | None:
    """Open seats, or None for an uncapped Circle."""
    return None if circle.max_members is None else circle.max_members - circle.member_count


def ineligibility_reason(member: Member, circle: Circle, now: datetime) -> str | None:
    """Why this Circle can't be recommended to this member, or None if it can.

    Checked in order. The first reason that applies is returned.
    """
    if circle.id in member.circle_ids:
        return "already a member"
    if circle.access != "public":
        return "unlisted"          # unlisted Circles opted out of discovery
    if is_full(circle):
        return "full"
    if days_since(circle.last_activity_at, now) > MAX_IDLE_DAYS:
        return "inactive"
    return None


# --- Steps 2 and 3: sort, then one per topic -------------------------------

def _sort_key(rec: Recommendation) -> tuple:
    # Tuples compare left to right, so an earlier key always outranks a later
    # one: topic before attendance, attendance before health. The negated id
    # keeps exact ties in ascending id order, so results are deterministic.
    return (rec.topic_match, rec.can_surely_attend, rec.health, -rec.circle.id)


def one_per_topic(ranked: Sequence[Recommendation], limit: int) -> list[Recommendation]:
    """Keep the best Circle per topic. Repeats only fill slots left over.

    Circles on the same topic are near-duplicates in this data (they share a
    description), so showing several would waste slots. This is Maximal
    Marginal Relevance with a yes-or-no similarity: same topic or not.
    """
    first_per_topic: list[Recommendation] = []
    repeats: list[Recommendation] = []
    seen_topics: set[str] = set()
    for rec in ranked:
        # A Circle without a topic is treated as its own group.
        topic = rec.circle.topic or f"untagged:{rec.circle.id}"
        (repeats if topic in seen_topics else first_per_topic).append(rec)
        seen_topics.add(topic)
    return (first_per_topic + repeats)[:limit]


# --- Step 4: explain -------------------------------------------------------

def reasons(member: Member, rec: Recommendation, snapshot: Snapshot) -> tuple[str, ...]:
    """Three short sentences a member sees under the Circle.

    Each one comes from a fact that actually ranked the Circle: why it fits her,
    proof it's alive, and how she can join. There are no scores and no claims
    the data can't support, such as "near you".
    """
    circle = rec.circle
    label = snapshot.topic_labels.get(circle.topic or "", circle.topic)

    if rec.topic_match:
        why = f"Focused on {label}, one of your interests."
    elif circle.topic:
        why = f"A good way to explore {label}."
    else:
        why = "A community Circle that isn't tied to one topic."

    idle_days = days_since(circle.last_activity_at, snapshot.taken_at)
    if idle_days <= 7:
        when = "this week"
    elif idle_days <= 30:
        when = "this month"
    else:
        when = f"{round(idle_days)} days ago"
    posts = circle.feed_posts_30d
    alive = f"Last active {when}, with {posts} post{'s' if posts != 1 else ''} in the last 30 days."

    meets = FORMAT_PHRASES[circle.format]
    join = "open to join" if circle.join_policy == "open" else "join by request"
    seats = seats_left(circle)
    scarcity = f", only {seats} spot{'s' if seats != 1 else ''} left" if seats is not None and seats <= 3 else ""
    how = f"{meets}, {join}{scarcity}."

    return (why, alive, how)


# --- The whole pipeline ----------------------------------------------------

def recommend(member: Member, snapshot: Snapshot, limit: int = DEFAULT_LIMIT) -> list[Recommendation]:
    """Ranked Circles for one member, best first, each with its reasons."""
    candidates = [
        Recommendation(
            circle=circle,
            topic_match=circle.topic in member.interests,
            can_surely_attend=can_surely_attend(circle),
            health=health(circle, snapshot),
        )
        for circle in snapshot.circles
        if ineligibility_reason(member, circle, snapshot.taken_at) is None
    ]
    ranked = sorted(candidates, key=_sort_key, reverse=True)
    picks = one_per_topic(ranked, limit)
    return [replace(rec, reasons=reasons(member, rec, snapshot)) for rec in picks]
