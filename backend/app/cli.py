from __future__ import annotations

import getpass
import sys

from app.auth.identity import create_owner, initialize, reset_owner_password


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli create-owner | reset-owner-password | init-identity-db")
        return 2
    command = sys.argv[1]
    if command == "init-identity-db":
        initialize()
        print("Identity database initialized.")
        return 0
    if command == "reset-owner-password":
        initialize()
        confirmation = input("Type RESET OWNER to confirm local recovery: ").strip()
        if confirmation != "RESET OWNER":
            print("Recovery cancelled.", file=sys.stderr)
            return 2
        password = getpass.getpass("New owner password (hidden): ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        try:
            user_id = reset_owner_password(password)
        except ValueError as exc:
            print(f"Recovery refused: {exc}", file=sys.stderr)
            return 1
        print(f"Owner password reset for account {user_id}. All sessions were revoked; next login requires password rotation.")
        return 0
    if command == "create-owner":
        initialize()
        login = input("Owner login [lshpek]: ").strip() or "lshpek"
        password = getpass.getpass("Initial owner password (hidden): ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        try:
            user_id = create_owner(login, password)
        except ValueError as exc:
            print(f"Bootstrap refused: {exc}", file=sys.stderr)
            return 1
        print(f"Owner created: {user_id}. The first login requires password rotation.")
        return 0
    print("Unknown command.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
