"""SQLite storage: build the database from the seed JSON, and read what the ranker needs."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.recommender import Circle, Member, Snapshot, enough_levels

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema.sql"
DATA_DIR = ROOT / "data"


def database_path() -> Path:
    """Where the SQLite file lives. Override with the CIRCLES_DB environment variable."""
    return Path(os.environ.get("CIRCLES_DB", ROOT / "circles.db"))


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path or database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def build_database(path: Path | None = None, data_dir: Path = DATA_DIR) -> Path:
    """Create a fresh database from schema.sql and the seed JSON files.

    The seed files are the source of truth, so the database is rebuilt from
    scratch rather than migrated.
    """
    path = path or database_path()
    path.unlink(missing_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _load_seed(conn, data_dir)
        conn.commit()
    return path


def _load_seed(conn: sqlite3.Connection, data_dir: Path) -> None:
    def read(name: str) -> list[dict]:
        return json.loads((data_dir / f"{name}.json").read_text())

    conn.executemany(
        "INSERT INTO topics (slug, label) VALUES (:slug, :label)",
        read("topics"),
    )

    users = read("users")
    conn.executemany(
        """INSERT INTO users (id, first_name, last_name, has_photo, bio, job_title, company,
                              industry, location, joined_at, profile_completeness)
           VALUES (:id, :first_name, :last_name, :has_photo, :bio, :job_title, :company,
                   :industry, :location, :joined_at, :profile_completeness)""",
        users,
    )
    conn.executemany(
        "INSERT INTO user_interests (user_id, topic_slug) VALUES (?, ?)",
        [(u["id"], slug) for u in users for slug in u["topic_interests"]],
    )

    circles = read("circles")
    conn.executemany(
        """INSERT INTO circles (id, name, slug, description, topic_slug, cover_image_url, format,
                                access, join_policy, max_members, member_count, created_at,
                                last_activity_at, feed_posts_30d, chat_messages_30d)
           VALUES (:id, :name, :slug, :description, :topic, :cover_image_url, :format,
                   :access, :join_policy, :max_members, :member_count, :created_at,
                   :last_activity_at, :feed_posts_30d, :chat_messages_30d)""",
        circles,
    )
    conn.executemany(
        "INSERT INTO circle_tags (circle_id, topic_slug) VALUES (?, ?)",
        # dict.fromkeys drops repeated tags (Circle 17 lists one twice) and keeps their order.
        [(c["id"], tag) for c in circles for tag in dict.fromkeys(c["tags"])],
    )

    conn.executemany(
        """INSERT INTO memberships (user_id, circle_id, role, joined_at)
           VALUES (:user_id, :circle_id, :role, :joined_at)""",
        read("memberships"),
    )
    conn.executemany(
        """INSERT INTO posts (id, circle_id, author_user_id, body, reaction_count,
                              comment_count, save_count, created_at)
           VALUES (:id, :circle_id, :author_user_id, :body, :reaction_count,
                   :comment_count, :save_count, :created_at)""",
        read("activity"),
    )


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def snapshot_time(conn: sqlite3.Connection) -> datetime:
    """The latest timestamp in the activity data.

    The seed data is a frozen snapshot, so "now" is the moment it was taken.
    Using the wall clock would age every Circle by however long ago the data
    was generated. In production this would simply be the current time.
    """
    row = conn.execute(
        """SELECT ts FROM (SELECT last_activity_at AS ts FROM circles
                           UNION ALL SELECT created_at FROM posts)
           ORDER BY julianday(ts) DESC LIMIT 1"""
    ).fetchone()
    return parse_timestamp(row["ts"])


def load_snapshot(conn: sqlite3.Connection) -> Snapshot:
    """All Circles with their activity, plus the topic labels."""
    taken_at = snapshot_time(conn)
    rows = conn.execute(
        """SELECT c.*,
                  COUNT(p.id)                        AS recent_posts,
                  COALESCE(SUM(p.reaction_count), 0) AS recent_reactions,
                  COALESCE(SUM(p.comment_count), 0)  AS recent_comments,
                  COALESCE(SUM(p.save_count), 0)     AS recent_saves
           FROM circles c
           LEFT JOIN posts p
             ON p.circle_id = c.id
            AND julianday(p.created_at) > julianday(:taken_at) - 30
           GROUP BY c.id
           ORDER BY c.id""",
        {"taken_at": taken_at.isoformat()},
    ).fetchall()
    circles = tuple(
        Circle(
            id=r["id"],
            name=r["name"],
            topic=r["topic_slug"],
            format=r["format"],
            access=r["access"],
            join_policy=r["join_policy"],
            max_members=r["max_members"],
            member_count=r["member_count"],
            last_activity_at=parse_timestamp(r["last_activity_at"]),
            feed_posts_30d=r["feed_posts_30d"],
            chat_messages_30d=r["chat_messages_30d"],
            recent_posts=r["recent_posts"],
            recent_reactions=r["recent_reactions"],
            recent_comments=r["recent_comments"],
            recent_saves=r["recent_saves"],
        )
        for r in rows
    )
    labels = {r["slug"]: r["label"] for r in conn.execute("SELECT slug, label FROM topics")}
    return Snapshot(taken_at=taken_at, circles=circles, topic_labels=labels, enough=enough_levels(circles))


def load_member(conn: sqlite3.Connection, user_id: int) -> Member | None:
    """A member's interests and Circles, or None if there's no such user."""
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        return None
    interests = conn.execute("SELECT topic_slug FROM user_interests WHERE user_id = ?", (user_id,))
    circles = conn.execute("SELECT circle_id FROM memberships WHERE user_id = ?", (user_id,))
    return Member(
        id=user_id,
        interests=frozenset(r["topic_slug"] for r in interests),
        circle_ids=frozenset(r["circle_id"] for r in circles),
    )
