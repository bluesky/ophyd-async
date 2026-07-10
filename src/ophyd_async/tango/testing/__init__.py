from pathlib import Path

from ._example_types import ExampleStrEnum, generate_random_trl_prefix
from ._launch import start_tango_device_servers, trl
from ._test_device import TangoTestDevice

#: Path to the standalone script serving this package's fixed `basic`/
#: `everything` test device catalog - pass to `start_tango_device_servers`. A
#: plain path constant rather than a module reference so nothing needs to
#: import `_tango_device_servers.py` (which would pull in `tango.server`/
#: `tango.test_context`) just to launch it.
DEVICE_SERVERS = Path(__file__).parent / "_tango_device_servers.py"

__all__ = [
    "DEVICE_SERVERS",
    "ExampleStrEnum",
    "TangoTestDevice",
    "generate_random_trl_prefix",
    "start_tango_device_servers",
    "trl",
]
