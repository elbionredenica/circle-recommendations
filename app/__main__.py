"""Print recommendations without running the server.

    python -m app 23
    python -m app 23 --limit 3
"""

import argparse
import sys

from app import db
from app.api import MAX_LIMIT, recommendations_response
from app.recommender import DEFAULT_LIMIT


def main() -> int:
    parser = argparse.ArgumentParser(description="Recommend Circles for one member.")
    parser.add_argument("user_id", type=int)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        choices=range(1, MAX_LIMIT + 1), metavar=f"1-{MAX_LIMIT}",
    )
    args = parser.parse_args()

    db.build_database()
    with db.connect() as conn:
        response = recommendations_response(conn, args.user_id, args.limit)
    if response is None:
        print(f"User {args.user_id} not found", file=sys.stderr)
        return 1
    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
