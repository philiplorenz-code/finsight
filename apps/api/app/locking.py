"""One lock order for owner financial mutations, shared by API and workers."""
from fastapi import HTTPException
from sqlalchemy import select, text, update

from .models import User


def lock_owner(db, user_id):
    if db.get_bind().dialect.name == "postgresql":
        # A repeatable-read snapshot established by authentication could predate
        # a lock wait. Reject unsupported isolation rather than use stale state.
        if db.scalar(text("SHOW transaction_isolation")) != "read committed":
            raise HTTPException(409, "Financial mutations require READ COMMITTED isolation")
    # SQLite has no row locks. Acquire its write lock before reading financial
    # state; a conflicting snapshot/write fails rather than applying stale data.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(User).where(User.id == user_id).values(owner_slot=User.owner_slot))
    owner = db.scalar(select(User).where(User.id == user_id).with_for_update()
                      .execution_options(populate_existing=True))
    if owner is None:
        raise HTTPException(404, "Owner not found")
    return owner
