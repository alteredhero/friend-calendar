"""Set, change or remove the shared password for your friend group.

    python set_password.py            prompt for a new password (typing is hidden)
    python set_password.py --clear    remove the password (calendar becomes open to anyone!)

Writes auth.json into the data folder (see paths.py). The server re-reads it on every request,
so there is no need to restart. Changing the password signs everyone out.

The installed .exe / tray menu uses run_gui() below: the same thing as a small dialog window.
"""
import getpass
import json
import sys

from passwords import hash_password
from paths import data_path

AUTH_PATH = data_path("auth.json")
MIN_LENGTH = 8


def write_auth(data: dict) -> None:
    with open(AUTH_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def save_password(password: str) -> None:
    write_auth({"password_hash": hash_password(password)})


def password_problem(first: str, second: str) -> str | None:
    """Why this pair isn't acceptable, or None if it is. Shared by the CLI and the dialog."""
    if len(first) < MIN_LENGTH:
        return f"Too short - use at least {MIN_LENGTH} characters (a few random words is great)."
    if first != second:
        return "Those didn't match, try again."
    return None


def prompt_password() -> str:
    while True:
        first = getpass.getpass("New group password: ").strip()
        second = getpass.getpass("Type it again: ").strip()
        if problem := password_problem(first, second):
            print(problem)
            continue
        return first


def run_gui() -> None:
    """A tiny 'choose the group password' window (used by the installer and the tray menu)."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Friend Calendar - group password")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    tk.Label(root, justify="left", padx=14, pady=10,
             text="Choose the password your friends will use to open the calendar.\n"
                  f"At least {MIN_LENGTH} characters. You can change it any time.").grid(
        row=0, column=0, columnspan=2)
    entries = []
    for row, label in enumerate(("Password", "Type it again"), start=1):
        tk.Label(root, text=label).grid(row=row, column=0, sticky="e", padx=(14, 6), pady=4)
        entry = tk.Entry(root, show="*", width=30)
        entry.grid(row=row, column=1, padx=(0, 14), pady=4)
        entries.append(entry)
    entries[0].focus_set()

    def save(event=None):
        first, second = (e.get().strip() for e in entries)
        if problem := password_problem(first, second):
            messagebox.showerror("Friend Calendar", problem, parent=root)
            return
        save_password(first)
        messagebox.showinfo("Friend Calendar", "Password saved. Share it with your friends.", parent=root)
        root.destroy()

    buttons = tk.Frame(root)
    buttons.grid(row=3, column=0, columnspan=2, pady=12)
    tk.Button(buttons, text="Save", width=10, command=save).pack(side="left", padx=6)
    tk.Button(buttons, text="Skip for now", width=12, command=root.destroy).pack(side="left", padx=6)
    root.bind("<Return>", save)
    root.mainloop()


def main() -> None:
    if "--clear" in sys.argv[1:]:
        write_auth({"password_hash": ""})
        print("Password removed - the calendar is now OPEN to anyone who can reach it.")
        return
    save_password(prompt_password())
    print(f"Saved to {AUTH_PATH}. Share the password with your friends - it is not stored in plain text.")


if __name__ == "__main__":
    main()
