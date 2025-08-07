import os
import pickle
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from random import choice
from typing import Any, Generic, TypeVar

import numpy as np
import pytest
from tango.asyncio_executor import set_global_executor

from ophyd_async.core import Array1D
from ophyd_async.tango.core import DevStateEnum
from ophyd_async.tango.testing import ExampleStrEnum
from ophyd_async.testing import (
    float_array_value,
    int_array_value,
)

T = TypeVar("T")


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


@dataclass
class AttributeData(Generic[T]):
    name: str
    py_type: type
    initial: T
    random_put_values: tuple[T, ...]
    cmd_name: str | None

    def random_value(self):
        return choice(self.random_put_values)


class ArrayData(AttributeData):
    def random_value(self):
        array = self.initial.copy()
        for idx in np.ndindex(array.shape):
            array[idx] = choice(self.random_put_values)
        return array


@pytest.fixture(scope="module")
def everything_signal_info():
    signal_info = {}

    def add_ads(
        name: str,
        tango_type: str,
        py_type: type,
        initial_scalar,
        initial_spectrum,
        choices,
    ):
        scalar_cmd = f"{name}_cmd" if tango_type != "DevUChar" else None
        signal_info[name] = AttributeData(
            name, py_type, initial_scalar, choices, scalar_cmd
        )
        spectrum_cmd = (
            f"{name}_spectrum_cmd"
            if tango_type not in ["DevUChar", "DevState", "DevEnum"]
            else None
        )
        signal_info[f"{name}_spectrum"] = ArrayData(
            f"{name}_spectrum",
            Array1D[py_type],
            initial_spectrum,
            choices,
            spectrum_cmd,
        )
        signal_info[f"{name}_image"] = ArrayData(
            f"{name}_image",
            np.ndarray[Any, np.dtype[py_type]],
            np.vstack((initial_spectrum, initial_spectrum)),
            choices,
            None,
        )

    add_ads(
        "str",
        "DevString",
        str,
        "test_string",
        np.array(["one", "two", "three"], dtype=str),
        ("four", "five", "six"),
    )
    add_ads(
        "bool",
        "DevBoolean",
        bool,
        True,
        np.array([False, True], dtype=bool),
        (False, True),
    )
    add_ads(
        "strenum",
        "DevEnum",
        ExampleStrEnum,
        ExampleStrEnum.B,
        np.array(
            [ExampleStrEnum.A.value, ExampleStrEnum.B.value, ExampleStrEnum.C.value],
        ),
        (ExampleStrEnum.A.value, ExampleStrEnum.B.value, ExampleStrEnum.C.value),
    )
    add_ads("int8", "DevShort", int, 1, int_array_value(np.int8), (1, 2, 3, 4, 5))
    add_ads("uint8", "DevUChar", int, 1, int_array_value(np.uint8), (1, 2, 3, 4, 5))
    add_ads("int16", "DevShort", int, 1, int_array_value(np.int16), (1, 2, 3, 4, 5))
    add_ads("uint16", "DevUShort", int, 1, int_array_value(np.uint16), (1, 2, 3, 4, 5))
    add_ads("int32", "DevLong", int, 1, int_array_value(np.int32), (1, 2, 3, 4, 5))
    add_ads("uint32", "DevULong", int, 1, int_array_value(np.uint32), (1, 2, 3, 4, 5))
    add_ads("int64", "DevLong64", int, 1, int_array_value(np.int64), (1, 2, 3, 4, 5))
    add_ads("uint64", "DevULong64", int, 1, int_array_value(np.uint64), (1, 2, 3, 4, 5))
    add_ads(
        "float32",
        "DevFloat",
        float,
        1.234,
        float_array_value(np.float32),
        (1.234, 2.345, 3.456),
    )
    add_ads(
        "float64",
        "DevDouble",
        float,
        1.234,
        float_array_value(np.float64),
        (1.234, 2.345, 3.456),
    )
    add_ads(
        "my_state",
        "DevState",
        DevStateEnum,
        DevStateEnum.INIT,
        np.array(  # TODO: make this work without the .values
            [DevStateEnum.INIT.value, DevStateEnum.ON.value, DevStateEnum.MOVING.value]
        ),
        (DevStateEnum.INIT.value, DevStateEnum.ON.value, DevStateEnum.MOVING.value),
    )

    return signal_info
