"""Encrypt legacy report results and rotate ciphertext to the active Fernet key."""

import argparse

from report_tasks import ReportTaskStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", required=True, help="Report task SQLite path or SQLAlchemy URL"
    )
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Rows per transaction (1-1000)"
    )
    args = parser.parse_args()

    store = ReportTaskStore(args.database)
    cursor = None
    total = 0
    while True:
        migrated, cursor = store.migrate_result_encryption(
            batch_size=args.batch_size, after_task_id=cursor
        )
        total += migrated
        if cursor is None:
            break
    print(f"Encrypted or rotated {total} report results.")


if __name__ == "__main__":
    main()
