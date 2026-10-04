#!/usr/bin/env bash
# Replace a database's data with four weeks of demo data (README, "Demo data").
# Keeps the shop row and its logins; everything else is deleted.
#
#   TARGET_URL=postgresql://...   the database to reset (staging), plain libpq URL
#   DATABASE_URL=...+psycopg://   an EMPTY local scratch database to build the data in
#   JWT_SECRET=...                any value: only signs tokens inside the build
#
# Runs from backend/. One transaction on the target: all of it, or none of it.
set -euo pipefail
here="$(dirname "$0")"
work="$(mktemp -d)"

echo "1. The target's schema must match this code"
want="$(alembic heads | awk '{print $1}' | sort | paste -sd, -)"
have="$(psql "$TARGET_URL" -At -c "select string_agg(version_num, ',' order by version_num) from alembic_version")"
if [ "$want" != "$have" ]; then
  echo "Schema differs: code has $want, target has $have. Apply migrations first." >&2
  exit 1
fi

echo "2. The shop and logins to keep"
shops="$(psql "$TARGET_URL" -At -c "select count(*) from shops")"
if [ "$shops" != "1" ]; then
  echo "Expected exactly one shop on the target, found $shops" >&2
  exit 1
fi
psql "$TARGET_URL" -At -f "$here/keep.sql" > "$work/keep.json"

echo "3. Build the data in the scratch database"
alembic upgrade heads > /dev/null
DEMO_KEEP="$work/keep.json" python -W ignore -m scripts.demo_data
local_url="${DATABASE_URL/+psycopg/}"
pg_dump "$local_url" --data-only --inserts --rows-per-insert=500 --no-owner --no-privileges \
  -T shops -T users -T refresh_tokens -T email_outbox -T messages -T alembic_version \
  -f "$work/data.sql"
# Session settings (search_path, timeouts) would outlive this load on a pooled
# connection and reach the app's queries: the dump is fully schema-qualified
# without them.
sed -i -E '/^(SET |SELECT pg_catalog.set_config)/d' "$work/data.sql"
python -m scripts.demo_export > "$work/extra.sql"

echo "4. Replace the target's data (one transaction)"
psql "$TARGET_URL" -v ON_ERROR_STOP=1 --single-transaction -q \
  -f "$here/wipe.sql" -f "$work/extra.sql" -f "$work/data.sql"

echo "5. What the target now holds"
psql "$TARGET_URL" -c "
  select (select count(*) from bills) bills, (select count(*) from orders) orders,
         (select count(*) from stock_ledger) ledger_rows, (select count(*) from users) logins,
         (select min(business_date) from bills) first_day, (select max(business_date) from bills) last_day"
rm -rf "$work"
