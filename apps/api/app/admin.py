"""Local admin commands, run inside the API container. Nothing here is reachable over HTTP.

    docker compose exec api python -m app.admin reset-password

Asks for the new password twice without echo, stores a new Argon2 hash and ends all sessions.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import delete, select

from .auth import hasher
from .db import SessionLocal
from .models import Session, User

MIN_LENGTH = 12


def reset_password(email: str | None, password: str) -> tuple[str, int]:
    if len(password) < MIN_LENGTH or len(password) > 1024:
        raise ValueError(f"Password must have {MIN_LENGTH} to 1024 characters")
    with SessionLocal() as db:
        users = list(db.scalars(select(User)))
        user = next((u for u in users if u.email == (email or "").strip().lower()), None) if email else (users[0] if len(users) == 1 else None)
        if user is None:
            raise LookupError("User not found")
        user.password_hash = hasher.hash(password)
        ended = db.execute(delete(Session).where(Session.user_id == user.id)).rowcount or 0
        db.commit()
        return user.email, ended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password", help="Set a new password for the owner and end all sessions")
    reset.add_argument("--email", help="Login email (optional when there is a single user)")
    args = parser.parse_args(argv)
    if args.command == "reset-password":
        first = getpass.getpass("Neues Passwort / new password: ")
        if first != getpass.getpass("Wiederholen / repeat: "):
            print("Die Passwörter stimmen nicht überein. / Passwords do not match.", file=sys.stderr)
            return 1
        try:
            email, ended = reset_password(args.email, first)
        except (ValueError, LookupError) as error:
            print(error, file=sys.stderr)
            return 1
        print(f"Passwort für {email} gesetzt, {ended} Sitzung(en) beendet. / Password set, sessions ended.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
