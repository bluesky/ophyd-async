"""Shared values/helpers with no Tango dependency.

Shared between the server (`_tango.py`) and client (`_test_device.py`) sides -
kept dependency-free deliberately, see `_tango.py`'s module docstring.
"""

import random
import string

from ophyd_async.core import StrictEnum


class ExampleStrEnum(StrictEnum):
    A = "AAA"
    B = "BBB"
    C = "CCC"


def generate_random_trl_prefix() -> str:
    """Generate a random Tango domain/family prefix for use in test devices."""
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    return f"test/{suffix}"
