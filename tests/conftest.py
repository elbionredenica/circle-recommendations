import os

import pytest

from app import db


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """A fresh database built from data/, shared by the whole test run."""
    path = tmp_path_factory.mktemp("db") / "circles.db"
    os.environ["CIRCLES_DB"] = str(path)   # read by the API at startup
    return db.build_database(path)


@pytest.fixture(scope="session")
def snapshot(db_path):
    with db.connect(db_path) as conn:
        return db.load_snapshot(conn)


@pytest.fixture(scope="session")
def member(db_path):
    """Look up a member by id: member(23)."""
    def load(user_id):
        with db.connect(db_path) as conn:
            return db.load_member(conn, user_id)
    return load


@pytest.fixture(scope="session")
def all_user_ids(db_path):
    with db.connect(db_path) as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM users ORDER BY id")]
