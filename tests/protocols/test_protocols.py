import tempfile

import mypy.api
import pytest
from ophyd import sim

from ophyd_async import protocols as bs_protocols


def test_readable():
    assert isinstance(sim.motor1, bs_protocols.AsyncReadable)
    assert isinstance(sim.det1, bs_protocols.AsyncReadable)
    assert not isinstance(sim.flyer1, bs_protocols.AsyncReadable)


def test_pausable():
    assert isinstance(sim.det1, bs_protocols.AsyncPausable)
