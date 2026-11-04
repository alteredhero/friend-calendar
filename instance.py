"""One running copy per data folder (so a roaming port can't leave two servers on one database).

A lock file in the data folder, held for the life of the process. The OS drops the lock if the
process dies, so there is never a stale lock to clean up. Works on Windows, macOS and Linux.
"""
import os

from paths import data_path

_handle = None


def acquire() -> bool:
    """True if we are now the only running copy for this data folder."""
    global _handle
    handle = open(data_path(".instance.lock"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _handle = handle
    return True


def release() -> None:
    """Give the lock up early (the tray does this just before it restarts itself)."""
    global _handle
    if _handle is None:
        return
    if os.name == "nt":
        import msvcrt
        _handle.seek(0)
        msvcrt.locking(_handle.fileno(), msvcrt.LK_UNLCK, 1)
    _handle.close()  # closing also releases an flock
    _handle = None
