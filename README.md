# Circle Recommendations

An API that recommends Lean In Circles to a member, with a short, true reason for each pick. It handles members with no history, near-duplicate Circles, and Circles that are full or inactive.

The reasoning behind the design is in [DESIGN.md](DESIGN.md).

## Quick start

Requires Python 3.11 or newer. Tested on 3.12 and 3.14.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api:app --reload
```

Then open http://127.0.0.1:8000/docs, or:

```bash
curl "http://127.0.0.1:8000/users/23/recommendations?limit=5"
```

The server rebuilds `circles.db` from `data/` every time it starts, so the database always matches the seed files.

To see recommendations without running the server:

```bash
python -m app 23 --limit 3
```

## Tests

```bash
pytest
```

The tests cover:

- the four scenarios from the assignment: cold start (user 42), obvious matches (user 7), duplicate Circles (user 15), and full or inactive Circles (user 23)
- rules checked for all 100 members: every pick is joinable and live, topic matches come first, no topic repeats, and every pick has three reasons
- each judgment call in DESIGN.md, varied across its range, with the four scenarios checked at every value
- the API: response shape, the cold-start hint, limit validation, and the 404 for unknown users

## API

### `GET /users/{user_id}/recommendations`

| Query parameter | Default | Allowed |
|---|---|---|
| `limit` | 5 | 1 to 20 |

Example, user 23 with `limit=2`:

```json
{
  "user_id": 23,
  "personalized": true,
  "hint": null,
  "results": [
    {
      "rank": 1,
      "circle_id": 22,
      "name": "Level Up Collective",
      "topic": "getting-promoted",
      "format": "hybrid",
      "join_policy": "request",
      "member_count": 14,
      "seats_left": 6,
      "reasons": [
        "Focused on Getting promoted, one of your interests.",
        "Last active this week, with 8 posts in the last 30 days.",
        "Meets in person and online, join by request."
      ],
      "ranking": { "topic_match": true, "can_surely_attend": true, "health": 0.922 }
    },
    {
      "rank": 2,
      "circle_id": 11,
      "name": "The Negotiation Table",
      "topic": "negotiation",
      "format": "hybrid",
      "join_policy": "open",
      "member_count": 15,
      "seats_left": 10,
      "reasons": [
        "A good way to explore Negotiation.",
        "Last active this week, with 13 posts in the last 30 days.",
        "Meets in person and online, open to join."
      ],
      "ranking": { "topic_match": false, "can_surely_attend": true, "health": 0.978 }
    }
  ]
}
```

- **`reasons`** are what a member would see under the Circle.
- **`ranking`** holds the three sort keys, compared in order, so you can see why each Circle ranks where it does.
- **`personalized`** is false for members who haven't picked any topics. For them, `hint` asks them to pick some.

| Status | When |
|---|---|
| 404 | The user doesn't exist |
| 422 | `limit` is outside 1 to 20 |

## Database schema

The full schema, with comments, is in [schema.sql](schema.sql).

| Table | What it holds | Key relationships |
|---|---|---|
| `topics` | The topic vocabulary | Primary key `slug` |
| `users` | Member profiles | |
| `user_interests` | Topics a member chose | `user_id` → `users`, `topic_slug` → `topics` |
| `circles` | Circle profile, capacity, and activity counters | `topic_slug` → `topics`, nullable |
| `circle_tags` | Free-form tags | `circle_id` → `circles`, `topic_slug` → `topics` |
| `memberships` | Who belongs to which Circle, and their role | Primary key `(user_id, circle_id)` |
| `posts` | Circle feed posts and their engagement | `circle_id` → `circles`, `author_user_id` → `users` |

Why it's shaped this way:

- **Interests and tags are join tables, not lists.** The database checks that every topic reference exists and rejects duplicates, and questions like "how many members follow each topic?" are a single `GROUP BY`.
- **The activity counters stay on the `circles` row.** That's how the product maintains them. Engagement is computed from `posts`.
- **Leaders are memberships with `role = 'leader'`,** not a separate table.
- **Timestamps are ISO-8601 UTC text,** which SQLite's `julianday()` can do date math on.

Indexes, matched to the lookups the app makes (checked with `EXPLAIN QUERY PLAN`):

- **Her interests and her Circles** use the primary keys of `user_interests` and `memberships`, which both start with `user_id`.
- **Each Circle's posts from the last 30 days** use `posts (circle_id, julianday(created_at))`. It's built on the same expression the snapshot query filters on, so SQLite reads only the posts in the window.
- **There's no index on Circle topic.** The app scores all 40 Circles, so nothing looks them up by topic yet. At scale it's the first one to add (see DESIGN.md, "Production scale").

## Project layout

```
app/
  recommender.py   the ranking: filters, health, sort, one per topic, reasons (pure functions)
  db.py            builds SQLite from data/ and loads what the ranker needs
  api.py           FastAPI endpoint and response models
  __main__.py      command-line entry point (python -m app <user_id>)
data/              seed data provided with the assignment, unchanged
schema.sql         tables, relationships, and indexes
scripts/
  design_numbers.py  reproduces the numbers cited in DESIGN.md
tests/             scenario, rule, judgment-call, and API tests
```

## How I used AI

I built this with Claude Code. I set the direction and made the calls. Before any code, I had it write pseudocode for every step, with the math and a worked example, so I could check the logic first. I made sure numbers (design decisions) weren't assumed without proper rationale behind them, and where the data could settle a number, I measured it against memberships. Tags predicted membership no better than no match (largely because of how the seed data was generated), so I cut them. The in-person discount became a plain rule, because the math showed any realistic discount ranks Circles the same way. I also cut details that didn't help a member decide, like the leader's name.

`scripts/design_numbers.py` reproduces every number in DESIGN.md, so none of it rests on the AI's word.
