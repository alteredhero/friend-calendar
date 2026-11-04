import os
import socket
import subprocess
import sys

import pytest

import instance
import paths
import ports

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listener(host: str, port: int, reuse: bool = False) -> socket.socket:
    s = socket.socket()
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen()
    return s


# ---- ports ------------------------------------------------------------------------
def test_free_port_is_kept():
    port = free_port()
    assert ports.choose_port("0.0.0.0", port) == port


def test_busy_port_moves_to_a_later_one():
    port = free_port()
    with listener("0.0.0.0", port):
        chosen = ports.choose_port("0.0.0.0", port)
    assert port < chosen < port + ports.SEARCH_RANGE


def test_strict_ignores_the_clash():
    port = free_port()
    with listener("0.0.0.0", port):
        assert ports.choose_port("0.0.0.0", port, strict=True) == port


def test_skips_several_busy_ports_in_a_row():
    base = free_port()
    held = []
    try:
        for offset in range(3):
            try:
                held.append(listener("0.0.0.0", base + offset))
            except OSError:
                pytest.skip("neighbouring ports not available on this machine")
        assert ports.choose_port("0.0.0.0", base) >= base + len(held)
    finally:
        for sock in held:
            sock.close()


@pytest.mark.skipif(sys.platform == "darwin", reason="BSD lets a wildcard bind share a port with a loopback listener")
def test_loopback_only_listener_counts_as_busy():
    port = free_port()
    with listener("127.0.0.1", port):
        assert ports.choose_port("0.0.0.0", port) != port


@pytest.mark.skipif(os.name != "nt", reason="exclusive-bind behaviour is Windows-specific")
def test_reuseaddr_listener_counts_as_busy_on_windows():
    port = free_port()
    with listener("0.0.0.0", port, reuse=True):
        assert ports.choose_port("0.0.0.0", port) != port


def test_never_goes_past_the_last_port():
    chosen = ports.choose_port("0.0.0.0", 65535)
    assert 1 <= chosen <= 65535


# ---- one running copy per data folder ------------------------------------------------
PROBE = "import sys; sys.path.insert(0, %r); import instance; print(instance.acquire())" % ROOT
HOLDER = ("import sys; sys.path.insert(0, %r); import instance\n"
          "print(instance.acquire(), flush=True); sys.stdin.readline()" % ROOT)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(instance, "_handle", None)
    yield tmp_path
    instance.release()


def run_probe(folder) -> str:
    env = dict(os.environ, FRIEND_CALENDAR_DATA=str(folder))
    return subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True).stdout.strip()


def test_second_process_is_refused_while_the_first_runs(folder):
    env = dict(os.environ, FRIEND_CALENDAR_DATA=str(folder))
    holder = subprocess.Popen([sys.executable, "-c", HOLDER], env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "True"
        assert run_probe(folder) == "False"
    finally:
        holder.stdin.close()
        holder.wait(timeout=20)
    assert run_probe(folder) == "True"  # the OS dropped the lock when the holder exited: no stale lock


def test_release_hands_the_lock_over(folder):
    assert instance.acquire() is True
    assert run_probe(folder) == "False"
    instance.release()
    assert run_probe(folder) == "True"


def test_release_without_acquire_is_harmless(folder):
    instance.release()
