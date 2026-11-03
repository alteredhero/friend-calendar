"""Set, change or remove the shared password for your friend group.

    python set_password.py            prompt for a new password (typing is hidden)
    python set_password.py --clear    remove the password (calendar becomes open to anyone!)

Writes auth.json next to this script. The server re-reads it on every request, so there is
no need to restart. Changing the password signs everyone out.
"""
import getpass
import json
import os
import sys

from passwords import hash_password

AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.json")
MIN_LENGTH = 8


def write_auth(data: dict) -> None:
    with open(AUTH_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def prompt_password() -> str:
    while True:
        first = getpass.getpass("New group password: ").strip()
        if len(first) < MIN_LENGTH:
            print(f"Too short - use at least {MIN_LENGTH} characters (a few random words is great).")
            continue
        if first != getpass.getpass("Type it again: ").strip():
            print("Those didn't match, try again.")
            continue
        return first


def main() -> None:
    if "--clear" in sys.argv[1:]:
        write_auth({"password_hash": ""})
        print("Password removed - the calendar is now OPEN to anyone who can reach it.")
        return
    write_auth({"password_hash": hash_password(prompt_password())})
    print(f"Saved to {AUTH_PATH}. Share the password with your friends - it is not stored in plain text.")


if __name__ == "__main__":
    main()
