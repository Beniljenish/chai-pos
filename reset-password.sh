#!/usr/bin/env sh
# Sets a new password on every login in your LOCAL database (the Docker one).
# Keeps all your data. Run it from the chai-pos folder with Docker running:
#   ./reset-password.sh
# It asks for the password (nothing shows as you type) and stores nothing but its hash.
set -eu

printf "New password (8+ characters): "
stty -echo 2>/dev/null || true
read -r PW
stty echo 2>/dev/null || true
echo

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
from app.models import User
db = mark_system(SessionLocal())
users = db.scalars(select(User)).all()
for u in users:
    u.password_hash = hash_password(os.environ['PW'])
    u.must_change_password = False
db.commit()
print(f'Password changed for {len(users)} logins.')
"
echo "Open http://localhost:5173 and log in as the owner 9000000000 with it."
