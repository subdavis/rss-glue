"""User model for authentication."""

from datetime import datetime, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from rss_glue.models.db import UTCDateTime

# Password hasher using argon2
_hasher = PasswordHasher()


class User(SQLModel, table=True):
    """User account for authentication."""

    __tablename__ = "user"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a password using argon2."""
        return _hasher.hash(password)

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""
        try:
            _hasher.verify(self.password_hash, password)
            return True
        except VerifyMismatchError:
            return False
