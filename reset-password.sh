#!/usr/bin/env sh
# Sets a new password on every login in your LOCAL database (the Docker one).
# Keeps all your data. Run it from the chai-pos folder with Docker running:
#   ./reset-password.sh
# It asks for the password (nothing shows as you type: type it, then press Enter once)
# and stores nothing but its hash. To skip the prompt, give it on the command line,
# in SINGLE quotes so the shell leaves characters like ! alone:
#   NEW_PASSWORD='your password' ./reset-password.sh
set -eu

PW="${NEW_PASSWORD:-}"
if [ -z "$PW" ]; then
  printf "New password (8+ characters; typing is hidden, press Enter when done): "
  stty -echo 2>/dev/null || true
  read -r PW
  stty echo 2>/dev/null || true
  echo
fi

if [ "${#PW}" -lt 8 ]; then
  echo "That is shorter than 8 characters. Nothing was changed." >&2
  exit 1
fi

docker compose exec -T -e PW="$PW" api python -c "
import os
from sqlalchemy import select
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import PlatformAdmin, User
db = mark_system(SessionLocal())
users = [*db.scalars(select(User)).all(), *db.scalars(select(PlatformAdmin)).all()]
for u in users:
    u.password_hash = hash_password(os.environ['PW'])
    if hasattr(u, 'must_change_password'):
        u.must_change_password = False
db.commit()
print(f'Password changed for {len(users)} logins.')
"
echo "Open http://localhost:5173 and log in as the owner 9000000000 with it."
