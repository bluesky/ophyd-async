import re

import inflection
import pytest

from ophyd_async.core import Device, Signal

# Need to import them all so the subclass walking gets all subclasses
# If we forget then the full test suite will find the subclasses, but
# running just this test will only get the ones at the top of this file
from ophyd_async.epics import (
    adaravis,  # noqa
    adcore,
    adkinetix,  # noqa
    adpilatus,  # noqa
    adsimdetector,  # noqa
    advimba,  # noqa
)


def get_rec_subclasses(cls: type):
    yield cls
    for subcls in cls.__subclasses__():
        yield from get_rec_subclasses(subcls)


@pytest.mark.parametrize("cls", list(get_rec_subclasses(adcore.NDArrayBaseIO)))
async def test_regularly_named_attributes(cls: Device):
    io = cls("")
    for name, device in io.children():
        check_name(name, device)


def check_name(name: str, device: Device):
    if isinstance(device, Signal):
        pv = extract_last_pv_part(device.source)
        # remove trailing underscore from name,
        # used to resolve clashes with Bluesky terms
        name = name[:-1] if name.endswith("_") else name
        assert inflection.underscore(pv) == name
    else:
        for name, signal in device.children():
            check_name(name, signal)


def extract_last_pv_part(raw_pv):
    """Extracts prefices and _RBV suffices.

    e.g. extracts DEVICE from the following
    ca://DEVICE
    ca://SYSTEM:DEVICE
    ca://SYSTEM:DEVICE_RBV
    """
    pattern = re.compile(
        r"""
        ca://           # Literal prefix "ca://"
        (?:.*:)?        # Optional prefix ending with a colon (non-capturing)
        ([^:_]+)        # Capturing group: base name without colon or underscore
        (?:_RBV)?       # Optional "_RBV" suffix (non-capturing)
        $               # End of string
        """,
        re.VERBOSE,
    )

    match = pattern.search(raw_pv)
    return str(match.group(1) if match else None)
