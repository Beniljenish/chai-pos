"""Make a VAPID key pair for Web Push (the "your order is ready" phone notifications).

    python -m scripts.make_vapid_keys

Prints two lines to put in the server's environment (Vercel env vars, or a local .env file):
VAPID_PUBLIC_KEY (safe to share: the app hands it to browsers) and VAPID_PRIVATE_KEY (a secret,
like a password: never commit it, never paste it into chat). Keep the same pair for good:
changing it makes every phone's existing subscription stop working.
"""

from app.services import webpush


def main() -> None:
    public, private = webpush.generate_keys()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")


if __name__ == "__main__":
    main()
