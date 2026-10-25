"""HTTP API.

    GET /users/{user_id}/recommendations?limit=5

Run with `uvicorn app.api:app --reload`, then open /docs for interactive docs.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app import db
from app.recommender import DEFAULT_LIMIT, recommend, seats_left

MAX_LIMIT = 20
COLD_START_HINT = "Pick a few topics to get Circles chosen for you."


class Ranking(BaseModel):
    """The three sort keys, so a reader can see why a Circle ranks where it does."""
    topic_match: bool
    can_surely_attend: bool
    health: float


class CircleRecommendation(BaseModel):
    rank: int
    circle_id: int
    name: str
    topic: str | None
    format: str
    join_policy: str
    member_count: int
    seats_left: int | None
    reasons: list[str]
    ranking: Ranking


class RecommendationsResponse(BaseModel):
    user_id: int
    personalized: bool            # False when she has no topics to match yet
    hint: str | None              # set only for members who haven't picked topics
    results: list[CircleRecommendation]


def recommendations_response(conn: sqlite3.Connection, user_id: int, limit: int) -> RecommendationsResponse | None:
    """Rank Circles for one member and shape the response. None if the user doesn't exist."""
    member = db.load_member(conn, user_id)
    if member is None:
        return None
    # The snapshot is small here, so it's loaded per request. At scale, Circle
    # health would be precomputed and candidates looked up by topic.
    snapshot = db.load_snapshot(conn)
    picks = recommend(member, snapshot, limit)
    personalized = bool(member.interests)
    return RecommendationsResponse(
        user_id=user_id,
        personalized=personalized,
        hint=None if personalized else COLD_START_HINT,
        results=[
            CircleRecommendation(
                rank=rank,
                circle_id=rec.circle.id,
                name=rec.circle.name,
                topic=rec.circle.topic,
                format=rec.circle.format,
                join_policy=rec.circle.join_policy,
                member_count=rec.circle.member_count,
                seats_left=seats_left(rec.circle),
                reasons=list(rec.reasons),
                ranking=Ranking(
                    topic_match=rec.topic_match,
                    can_surely_attend=rec.can_surely_attend,
                    health=round(rec.health, 3),
                ),
            )
            for rank, rec in enumerate(picks, start=1)
        ],
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Rebuild from the seed files on every start, so the database always
    # matches data/.
    db.build_database()
    yield


app = FastAPI(
    title="Circle Recommendations",
    description="Ranks Lean In Circles for a member and explains each pick.",
    lifespan=lifespan,
)


@app.get("/users/{user_id}/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    user_id: int,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="How many Circles to return."),
) -> RecommendationsResponse:
    with db.connect() as conn:
        response = recommendations_response(conn, user_id, limit)
    if response is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return response
