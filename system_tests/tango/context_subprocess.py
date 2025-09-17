import pickle
import socket
import sys

from tango.test_context import MultiDeviceTestContext

if __name__ == "__main__":
    port = int(sys.argv[1])

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("localhost", port))

    pickled_args = sock.recv(1024)
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
        while sock.recv(1024):
            pass  # when connection closes subprocess should end
    sock.close()
