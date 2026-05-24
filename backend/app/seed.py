"""Idempotent seed of PoC users and global settings.

Run with ``python -m app.seed``. Safe to run repeatedly: users are upserted
by ``username`` and settings by ``key``.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.global_setting import GlobalSetting
from app.models.user import User
from app.services.pricing import seed_pricing

_USERS = [
    ("admin", "Admin User", "admin@example.com", ["admin"]),
    ("dev1", "Developer One", "dev1@example.com", ["developer"]),
    ("dev2", "Developer Two", "dev2@example.com", ["developer"]),
    ("ccowner1", "Cost Centre Owner One", "ccowner1@example.com", ["cco", "developer"]),
]

_SETTINGS = {
    "aws_region": "ap-southeast-2",
    "allowed_models": [
        "anthropic.claude-sonnet-4-6",
        "anthropic.claude-haiku-4-5",
    ],
    "default_key_expiry_days": 90,
    "default_rolling_limit": {"amount": 50.00, "period_days": 7},
    "default_lifetime_budget": 500.00,
}


def seed(db: Session) -> None:
    """Upsert the hard-coded users and default global settings."""
    for username, display_name, email, roles in _USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(
                User(
                    username=username,
                    display_name=display_name,
                    email=email,
                    password_hash=hash_password(username),
                    roles=roles,
                    is_active=True,
                )
            )
        else:
            user.display_name = display_name
            user.email = email
            user.roles = roles

    for key, value in _SETTINGS.items():
        setting = db.get(GlobalSetting, key)
        if setting is None:
            db.add(GlobalSetting(key=key, value=value))
        else:
            setting.value = value

    seed_pricing(db)

    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
