"""Review or prune expired terminal report tasks using an explicit UTC cutoff."""

import argparse
from datetime import datetime, timezone

from report_tasks import ReportTaskStore


def _cutoff_timestamp(value: str) -> float:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cutoff must be an ISO-8601 datetime") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise argparse.ArgumentTypeError("cutoff must include a timezone")
    return instant.astimezone(timezone.utc).timestamp()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", required=True, help="Report task SQLite path or SQLAlchemy URL"
    )
    parser.add_argument(
        "--before",
        required=True,
        type=_cutoff_timestamp,
        help="Explicit ISO-8601 UTC cutoff, for example 2026-01-01T00:00:00Z",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="Rows per transaction (1-1000)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Delete counted succeeded/failed tasks"
    )
    args = parser.parse_args()

    store = ReportTaskStore(args.database)
    count = store.count_terminal_tasks_before(args.before)
    if not args.apply:
        print(f"Would prune {count} terminal report tasks.")
        return
    deleted = 0
    while True:
        batch = store.prune_terminal_tasks_before(
            args.before, batch_size=args.batch_size
        )
        deleted += batch
        if batch < args.batch_size:
            break
    print(f"Pruned {deleted} terminal report tasks (initial count: {count}).")


if __name__ == "__main__":
    main()
