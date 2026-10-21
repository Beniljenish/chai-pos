#!/usr/bin/env sh
# Adds another shop and its owner's login to your LOCAL database, so a second outlet
# owner can join a food court. There is no sign-up screen: this is how a shop is made.
# Run it from the chai-pos folder with the app running (./local.sh):
#   ./new-outlet.sh
set -eu

printf "Outlet name (for example Anna Biryani): "
read -r NAME
printf "Owner's 10-digit mobile number: "
read -r PHONE
printf "Owner's name [Owner]: "
read -r OWNER
OWNER="${OWNER:-Owner}"
printf "Add a sample menu so they can try ordering? [Y/n]: "
read -r SAMPLE
case "$SAMPLE" in n | N) MENU=0 ;; *) MENU=1 ;; esac

docker compose exec -T \
  -e NEW_SHOP_NAME="$NAME" -e NEW_OWNER_PHONE="$PHONE" -e NEW_OWNER_NAME="$OWNER" -e SAMPLE_MENU="$MENU" \
  api python -m scripts.new_shop

echo
echo "Log in as $PHONE at http://localhost:5173 (no password in local test mode)."
echo "Use a private window, or log out first: a browser holds one login at a time."
echo "Then Manage -> Food court -> Join, and type the host's code."
