#!/usr/bin/env python3
"""Reset a user's password from the command line."""

import getpass
import sys

from sqlmodel import Session, select

from rss_glue.database import engine
from rss_glue.models.user import User


def main():
    if len(sys.argv) < 2:
        # List available users
        with Session(engine) as session:
            users = session.exec(select(User)).all()
            if not users:
                print("No users in database.")
                sys.exit(1)
            print("Available users:")
            for user in users:
                print(f"  - {user.username}")
            print(f"\nUsage: uv run python -m rss_glue.scripts.reset_password <username>")
        sys.exit(1)

    username = sys.argv[1]

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user:
            print(f"Error: User '{username}' not found.")
            sys.exit(1)

        # Prompt for new password
        password = getpass.getpass("New password: ")
        if len(password) < 8:
            print("Error: Password must be at least 8 characters.")
            sys.exit(1)

        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Error: Passwords do not match.")
            sys.exit(1)

        # Update password
        user.password_hash = User.hash_password(password)
        session.add(user)
        session.commit()

        print(f"Password updated for user '{username}'.")


if __name__ == "__main__":
    main()
