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
    for name, signal in io.children():
        assert isinstance(signal, Signal)
        # Strip off the ca:// prefix and an _RBV suffix
        pv = signal.source.split("://")[-1].split("_RBV")[0]
        assert inflection.underscore(pv) == name
