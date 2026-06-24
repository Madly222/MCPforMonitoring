#!/usr/bin/env python3
"""
User management CLI.

Manage the runtime user store from the console — useful for bootstrapping the
first superadmin or recovering access. Run from the project root:

    python scripts/manage_users.py list
    python scripts/manage_users.py add <username> <password> <role>
    python scripts/manage_users.py passwd <username> <password>
    python scripts/manage_users.py role <username> <role>
    python scripts/manage_users.py delete <username>

Roles: superadmin | admin | operator
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web.users import get_user_store, VALID_ROLES


def usage():
    print(__doc__)
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()

    store = get_user_store()
    cmd = sys.argv[1]

    try:
        if cmd == "list":
            for u in store.list_users():
                print(f"  {u['username']:20} {u['role']:12} updated={u.get('updated_at', '')}")
            print(f"\nTotal: {len(store.list_users())} | superadmins: {store.count_superadmins()}")

        elif cmd == "add" and len(sys.argv) == 5:
            _, _, username, password, role = sys.argv
            store.add_user(username, password, role)
            print(f"Created user '{username}' with role '{role}'")

        elif cmd == "passwd" and len(sys.argv) == 4:
            _, _, username, password = sys.argv
            store.set_password(username, password)
            print(f"Password changed for '{username}'")

        elif cmd == "role" and len(sys.argv) == 4:
            _, _, username, role = sys.argv
            store.set_role(username, role)
            print(f"Role changed for '{username}' to '{role}'")

        elif cmd == "delete" and len(sys.argv) == 3:
            _, _, username = sys.argv
            if store.get_role(username) == "superadmin" and store.count_superadmins() <= 1:
                print("Refusing to delete the last superadmin.")
                sys.exit(1)
            store.delete_user(username)
            print(f"Deleted user '{username}'")

        else:
            usage()

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
