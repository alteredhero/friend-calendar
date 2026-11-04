"""Find a TCP port for the server.

If the preferred port is busy we walk upward (8032, 8033, ...) until one is free, so a clash
with some other program never stops the calendar from starting. Pass strict=True to skip the
search and use exactly the port asked for (what you want behind a tunnel that points at one port).
"""
import os
import socket

SEARCH_RANGE = 50  # how many consecutive ports to try before letting the OS pick one


def _in_use(host: str, port: int) -> bool:
    """True if something already owns the port: just try to bind it, then let go.

    On Windows the bind is *exclusive*. A plain wildcard bind (0.0.0.0) can succeed even while
    another program listens on 127.0.0.1:port; the exclusive flag makes that count as a clash.
    (Don't replace this with a connect() probe: Windows takes ~2 s to refuse a closed port.)
    """
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:  # match asyncio's own listening socket
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def choose_port(host: str, preferred: int, strict: bool = False) -> int:
    if strict:
        return preferred
    for port in range(preferred, min(preferred + SEARCH_RANGE, 65536)):
        if not _in_use(host, port):
            return port
    with socket.socket() as sock:  # nothing free nearby: ask the OS for any free port
        sock.bind((host, 0))
        return sock.getsockname()[1]
