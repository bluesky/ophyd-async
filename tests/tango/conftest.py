import os
import pickle
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tango.asyncio_executor import set_global_executor


@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


def pytest_collection_modifyitems(config, items):
    tango_dir = os.path.join("tests", "tango")
    for item in items:
        if tango_dir in str(item.fspath):
            if sys.version_info >= (3, 12):
                item.add_marker(
                    pytest.mark.skip(
                        reason="Tango is currently not supported on Python 3.12: https://github.com/bluesky/ophyd-async/issues/681"
                    )
                )


class TangoSubprocessHelper:
    def __init__(self, args):
        self._args = args

    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("", 0))
        port = str(self.sock.getsockname()[1])
        self.sock.listen(1)
        subprocess_path = str(Path(__file__).parent / "context_subprocess.py")
        self.process = subprocess.Popen([sys.executable, subprocess_path, port])
        self.conn, _ = self.sock.accept()
        self.conn.send(pickle.dumps(self._args))
        self.trls = pickle.loads(self.conn.recv(1024))
        return self

    def __exit__(self, A, B, C):
        self.conn.close()
        self.sock.close()
        self.process.communicate()


@pytest.fixture(scope="module")
def subprocess_helper():
    return TangoSubprocessHelper
