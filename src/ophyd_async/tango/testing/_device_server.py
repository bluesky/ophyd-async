"""Provides a mechanism for creating a Tango device server executed as a subprocess.

The device server is run up using the Tango MultiDeviceTestContext which allows it
to run standalone without a Tango Database.  Multiple Tango Devices can be loaded into
the single device server instance.
"""

import os
import pickle
import random
import socket
import string
import subprocess
import sys
from pathlib import Path
from typing import cast

from tango.test_context import MultiDeviceTestContext

_ACCEPT_TIMEOUT = 30.0  # seconds to wait for subprocess to connect back
_COMMUNICATE_TIMEOUT = 10.0  # seconds to wait for subprocess to exit cleanly


def generate_random_trl_prefix() -> str:
    """Generate a random Tango domain/family/member prefix for use in test devices."""
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    return f"test/{suffix}"


def _recv_all(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed before all bytes were received")
        buf += chunk
    return buf


def _send_pickled(conn: socket.socket, obj: object) -> None:
    data = pickle.dumps(obj)
    conn.sendall(len(data).to_bytes(4, "big") + data)


def _recv_pickled(conn: socket.socket) -> object:
    n = int.from_bytes(_recv_all(conn, 4), "big")
    return pickle.loads(_recv_all(conn, n))


class TangoSubprocessDeviceServer:
    def __init__(self, args):
        self._args = args
        self.trls: dict[str, str] = {}

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        port = str(self.sock.getsockname()[1])
        self.sock.listen(1)
        subprocess_path = str(Path(__file__).parent / "_device_server.py")
        self.process = subprocess.Popen(
            [sys.executable, subprocess_path, port],
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        )
        self.sock.settimeout(_ACCEPT_TIMEOUT)
        self.conn, _ = self.sock.accept()
        self.sock.settimeout(None)
        _send_pickled(self.conn, self._args)
        self.trls = cast(dict[str, str], _recv_pickled(self.conn))
        return self

    def disconnect(self):
        self.conn.close()
        self.sock.close()
        try:
            self.process.communicate(timeout=_COMMUNICATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


if __name__ == "__main__":
    port = int(sys.argv[1])

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", port))

    context_args = _recv_pickled(sock)

    device_names = []
    for arg_dict in context_args:
        for device in arg_dict["devices"]:
            device_names.append(device["name"])

    trls = {}
    with MultiDeviceTestContext(context_args, process=False) as context:
        for name in device_names:
            trls[name] = context.get_device_access(name)
        _send_pickled(sock, trls)
        while sock.recv(1):
            pass  # when connection closes subprocess should end
    sock.close()
