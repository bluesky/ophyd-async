import pickle
import socket
import subprocess
import sys
from pathlib import Path

from tango.test_context import MultiDeviceTestContext

"""
This file provides a mechanism for creating a Tango demo device server executed as a
python subprocess.
The demo device server is run up using the Tango MultiDeviceTestContext which allows it
to run standalone without a Tango Database.  Multiple Tango Devices can be loaded into
the single device server instance.
"""

BYTES_TO_READ = 2048


class TangoSubprocessDeviceServer:
    def __init__(self, args):
        self._args = args

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("", 0))
        port = str(self.sock.getsockname()[1])
        self.sock.listen(1)
        subprocess_path = str(Path(__file__).parent / "_device_server.py")
        self.process = subprocess.Popen([sys.executable, subprocess_path, port])
        self.conn, _ = self.sock.accept()
        self.conn.send(pickle.dumps(self._args))
        self.trls = pickle.loads(self.conn.recv(BYTES_TO_READ))
        return self

    def disconnect(self):
        self.conn.close()
        self.sock.close()
        self.process.communicate()


if __name__ == "__main__":
    port = int(sys.argv[1])

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("localhost", port))

    pickled_args = sock.recv(BYTES_TO_READ)
    context_args = pickle.loads(pickled_args)

    device_names = []
    for arg_dict in context_args:
        for device in arg_dict["devices"]:
            device_names.append(device["name"])

    trls = {}
    with MultiDeviceTestContext(context_args, process=False) as context:
        for name in device_names:
            trls[name] = context.get_device_access(name)
        sock.send(pickle.dumps(trls))
        while sock.recv(BYTES_TO_READ):
            pass  # when connection closes subprocess should end
    sock.close()
