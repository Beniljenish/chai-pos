"""Give the sample dishes (Masala tea, Orange juice) their picture and description in every shop
that was made before pictures existed, in whatever database DATABASE_URL points at.

    python -m scripts.add_dish_pictures

Only blanks are filled: a dish an owner has described, or given a picture of their own, is left
alone. Safe to run again. `./local.sh` runs it, so a computer that already has demo data gets the
pictures on its next start.
"""

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.services.sample import add_sample_pictures


def main() -> None:
    with mark_system(SessionLocal()) as db:
        n = add_sample_pictures(db)
    print(f"Added a picture and description to {n} dish{'' if n == 1 else 'es'}.")


if __name__ == "__main__":
    main()
