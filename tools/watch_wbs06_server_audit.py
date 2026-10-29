#!/usr/bin/env python3
"""Show recent and new scale-server audit events without exposing credentials.

Usage: python3 tools/watch_wbs06_server_audit.py [--once] [--db PATH]
The watcher opens SQLite read-only and never reads scale secrets or payloads.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


DEFAULT_DB = Path(__file__).resolve().parents[1] / "local/data/yow.sqlite3"


def event_rows(db: sqlite3.Connection, after: int, limit: int = 100):
    return db.execute(
        "SELECT id, endpoint, outcome, received_at, detail "
        "FROM sync_audit WHERE id>? ORDER BY id LIMIT ?",
        (after, limit),
    ).fetchall()


def show(row) -> None:
    ident, endpoint, outcome, stamp, detail = row
    local = datetime.fromtimestamp(stamp).astimezone().strftime("%H:%M:%S %Z")
    suffix = f" — {detail}" if detail else ""
    print(f"{local}  {endpoint}: {outcome}{suffix}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path,
                        default=DEFAULT_DB)
    parser.add_argument("--once", action="store_true", help="print recent events and exit")
    parser.add_argument("--recent", type=int, default=5,
                        help="number of historical events to show first (default: 5)")
    args = parser.parse_args()
    if args.recent < 0 or args.recent > 100:
        parser.error("--recent must be between 0 and 100")
    path = args.db.expanduser().resolve()
    if not path.is_file():
        parser.error(f"database not found: {path}")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            latest = db.execute("SELECT COALESCE(MAX(id),0) FROM sync_audit").fetchone()[0]
            after = max(0, latest - args.recent)
            while True:
                rows = event_rows(db, after)
                for row in rows:
                    show(row)
                    after = row[0]
                if args.once:
                    return 0
                if not rows:
                    time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped watching; server and database unchanged.")
        return 0
    except sqlite3.Error as error:
        print(f"Cannot read server audit: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
