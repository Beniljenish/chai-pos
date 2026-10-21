#!/usr/bin/env sh
# One command for local development: starts the database, API and app in Docker,
# loads four weeks of demo data the first time, and says where to open it.
#   ./local.sh
# Needs Docker Desktop running. Nothing here reaches staging.
set -eu

docker compose up --build -d

echo "Waiting for the API (the first run installs packages and can take a few minutes)..."
tries=0
until docker compose exec -T api python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -gt 180 ]; then
    echo "The API did not start. See why with: docker compose logs api" >&2
    exit 1
  fi
  sleep 2
done

has_shop=$(docker compose exec -T db psql -U chai -d chai_pos -tAc "select count(*) from shops" | tr -d '[:space:]')
if [ "$has_shop" = "0" ]; then
  printf "Pick a password for the demo logins (8+ characters; it is not stored anywhere else): "
  stty -echo 2>/dev/null || true
  read -r pw
  stty echo 2>/dev/null || true
  echo
  echo "Loading four weeks of demo data (about a minute)..."
  docker compose exec -T -e DEMO_PASSWORD="$pw" api python -m scripts.local_demo
else
  echo "Demo data is already loaded."
fi

echo
echo "Open  http://localhost:5173  and log in as the owner 9000000000."
echo "The app takes a minute to appear the first time. Stop with: docker compose down"
