-- Schema for the Circle recommender.
--
-- One table per entity in the seed data, plus two join tables for the
-- many-to-many topic links (member interests and Circle tags). Topic slugs are
-- the shared vocabulary, so every topic reference is a foreign key to topics.
--
-- Timestamps are ISO-8601 UTC strings (e.g. 2026-09-21T00:00:00.000Z), which
-- SQLite's julianday() understands for date arithmetic.

PRAGMA foreign_keys = ON;

CREATE TABLE topics (
    slug  TEXT PRIMARY KEY,                -- e.g. 'negotiation'
    label TEXT NOT NULL                    -- e.g. 'Negotiation'
);

CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    first_name           TEXT NOT NULL,
    last_name            TEXT NOT NULL,
    has_photo            INTEGER NOT NULL CHECK (has_photo IN (0, 1)),
    bio                  TEXT,
    job_title            TEXT,
    company              TEXT,
    industry             TEXT,
    location             TEXT,
    joined_at            TEXT NOT NULL,
    profile_completeness REAL NOT NULL CHECK (profile_completeness BETWEEN 0 AND 1)
);

-- Topics a member chose. Empty for new members (the cold-start case).
CREATE TABLE user_interests (
    user_id    INTEGER NOT NULL REFERENCES users (id),
    topic_slug TEXT    NOT NULL REFERENCES topics (slug),
    PRIMARY KEY (user_id, topic_slug)
);

CREATE TABLE circles (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    slug              TEXT NOT NULL UNIQUE,
    description       TEXT,
    topic_slug        TEXT REFERENCES topics (slug),   -- NULL for Circles without a topic
    cover_image_url   TEXT,
    format            TEXT NOT NULL CHECK (format IN ('in_person', 'virtual', 'hybrid')),
    access            TEXT NOT NULL CHECK (access IN ('public', 'unlisted')),
    join_policy       TEXT NOT NULL CHECK (join_policy IN ('open', 'request')),
    max_members       INTEGER CHECK (max_members IS NULL OR max_members > 0),  -- NULL = uncapped
    member_count      INTEGER NOT NULL CHECK (member_count >= 0),
    created_at        TEXT NOT NULL,
    last_activity_at  TEXT NOT NULL,
    -- Rolling counters kept on the row, the way the product maintains them.
    feed_posts_30d    INTEGER NOT NULL CHECK (feed_posts_30d >= 0),
    chat_messages_30d INTEGER NOT NULL CHECK (chat_messages_30d >= 0)
);

-- Free-form tags. Stored for completeness. The ranker doesn't use them
-- (see DESIGN.md, "Signals").
CREATE TABLE circle_tags (
    circle_id  INTEGER NOT NULL REFERENCES circles (id),
    topic_slug TEXT    NOT NULL REFERENCES topics (slug),
    PRIMARY KEY (circle_id, topic_slug)
);

-- A Circle's leaders are members with role = 'leader'.
CREATE TABLE memberships (
    user_id   INTEGER NOT NULL REFERENCES users (id),
    circle_id INTEGER NOT NULL REFERENCES circles (id),
    role      TEXT    NOT NULL CHECK (role IN ('member', 'leader')),
    joined_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, circle_id)       -- one row per member per Circle; also serves "Circles this member is in"
);

-- Circle feed posts (activity.json).
CREATE TABLE posts (
    id             INTEGER PRIMARY KEY,
    circle_id      INTEGER NOT NULL REFERENCES circles (id),
    author_user_id INTEGER NOT NULL REFERENCES users (id),
    body           TEXT    NOT NULL,
    reaction_count INTEGER NOT NULL CHECK (reaction_count >= 0),
    comment_count  INTEGER NOT NULL CHECK (comment_count >= 0),
    save_count     INTEGER NOT NULL CHECK (save_count >= 0),
    created_at     TEXT    NOT NULL
);

-- The primary keys already cover a member's interests and her Circles. This
-- index covers each Circle's posts from the last 30 days. It's built on
-- julianday(created_at), the same expression the snapshot query filters on,
-- so SQLite seeks straight to the window instead of checking every post.
CREATE INDEX idx_posts_circle_created ON posts (circle_id, julianday(created_at));
