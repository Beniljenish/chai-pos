"""A backup you have not restored is a hope, not a backup (README, "9.21").

Dumps the live database, restores the dump into a throwaway database on a *different* Postgres
(for example one on your own computer), and compares the number of rows in every table. If the
counts match, the backup can be restored. The throwaway database is dropped at the end.

  python -m scripts.restore_check --source "$SOURCE_URL" --scratch "$SCRATCH_URL"

SOURCE_URL is the database to back up (only ever read: pg_dump). SCRATCH_URL is a server where you
may create and drop databases, such as a local Postgres (".../postgres"). It never touches the
source's server, so a mistake here cannot damage the live data. Passwords stay in your own shell:
nothing is written to a file, and the URLs are not printed.

Needs pg_dump, pg_restore and psql on the PATH. Supabase's own backups are separate: check your
plan for how long it keeps them and whether it offers point-in-time restore.
"""

import argparse
import re
import shutil
import subprocess  # noqa: S404 (runs only pg_dump and pg_restore, with the owner's own URLs)
import sys
import uuid

import psycopg

PG_DUMP = shutil.which("pg_dump") or "pg_dump"
PG_RESTORE = shutil.which("pg_restore") or "pg_restore"


def libpq(url: str) -> str:
    """The SQLAlchemy form (postgresql+psycopg://) as a plain libpq URL."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


def with_db(url: str, db: str) -> str:
    return re.sub(r"(postgresql://[^/]*)/[^?]*", rf"\1/{db}", libpq(url), count=1)


def _server(url: str) -> str:
    return libpq(url).split("@")[-1].split("/")[0].lower()


def _server(url: str) -> str:
    return libpq(url).split("@")[-1].split("/")[0].lower()


def counts(url: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with psycopg.connect(libpq(url)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        for (table,) in cur.fetchall():
            cur.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608 (names from the catalogue)
            out[table] = cur.fetchone()[0]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--source", required=True, help="the database to back up (read only)")
    ap.add_argument(
        "--scratch", required=True, help="a server where a throwaway database may be made"
    )
    ap.add_argument(
        "--allow-same-server",
        action="store_true",
        help="only for trying this out on your own computer: source and scratch on one server",
    )
    args = ap.parse_args(argv)
    if not args.allow_same_server and _server(args.source) == _server(args.scratch):
        print("The scratch server must be a different server from the source.", file=sys.stderr)
        return 2
    name = f"restore_check_{uuid.uuid4().hex[:8]}"
    admin = libpq(args.scratch)
    scratch_db = with_db(args.scratch, name)
    dump = subprocess.run(  # noqa: S603
        [PG_DUMP, "--format=custom", "--no-owner", "--no-privileges", libpq(args.source)],
        capture_output=True,
    )
    if dump.returncode != 0:
        print("pg_dump failed:", dump.stderr.decode()[:300], file=sys.stderr)
        return 1
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        restore = subprocess.run(  # noqa: S603
            [PG_RESTORE, "--no-owner", "--no-privileges", "--exit-on-error", "-d", scratch_db],
            input=dump.stdout,
            capture_output=True,
        )
        if restore.returncode != 0:
            print("pg_restore failed:", restore.stderr.decode()[:300], file=sys.stderr)
            return 1
        before, after = counts(args.source), counts(scratch_db)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    wrong = {t: (before[t], after.get(t)) for t in before if before[t] != after.get(t)}
    if wrong:
        print("MISMATCH: these tables differ (source, restored):", wrong, file=sys.stderr)
        return 1
    rows = sum(before.values())
    print(f"OK: {len(before)} tables and {rows} rows restored and counted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
