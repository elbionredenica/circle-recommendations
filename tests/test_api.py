import pytest
from fastapi.testclient import TestClient

from app.api import app


@pytest.fixture(scope="module")
def client(db_path):
    # Entering the client runs the app's startup, which builds the database
    # at CIRCLES_DB (set by the db_path fixture).
    with TestClient(app) as c:
        yield c


def test_returns_ranked_circles_with_reasons(client):
    res = client.get("/users/23/recommendations")
    assert res.status_code == 200
    body = res.json()

    assert body["user_id"] == 23
    assert body["personalized"] is True
    assert body["hint"] is None
    assert [r["rank"] for r in body["results"]] == [1, 2, 3, 4, 5]

    first = body["results"][0]
    assert first["circle_id"] == 22
    assert first["ranking"]["topic_match"] is True
    assert first["ranking"]["can_surely_attend"] is True
    assert 0 <= first["ranking"]["health"] <= 1
    assert len(first["reasons"]) == 3


def test_cold_start_is_marked_not_personalized(client):
    body = client.get("/users/42/recommendations").json()
    assert body["personalized"] is False
    assert body["hint"]


def test_limit_controls_list_length(client):
    assert len(client.get("/users/7/recommendations?limit=3").json()["results"]) == 3


@pytest.mark.parametrize("limit", [0, 21])
def test_limit_outside_1_to_20_is_rejected(client, limit):
    assert client.get(f"/users/7/recommendations?limit={limit}").status_code == 422


def test_unknown_user_returns_404(client):
    res = client.get("/users/999/recommendations")
    assert res.status_code == 404
    assert res.json() == {"detail": "User 999 not found"}
