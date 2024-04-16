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


# I think the commented out tests pass because __getattr__ is implemented, but not sure
@pytest.mark.skip(reason="ophyd missing py.typed to communicate type hints to mypy")
@pytest.mark.parametrize(
    "type_, hardware, pass_",
    [
        ("Readable", "ABDetector(name='hi')", True),
        ("Readable", "SynAxis(name='motor1')", True),
        ("Readable", "TrivialFlyer()", False),
        ("Configurable", "ABDetector(name='hi')", True),
        ("Pausable", "ABDetector(name='hi')", True),
    ],
)
def test_mypy(type_, hardware, pass_):
    template = f"""
from ophyd_async import protocols as bs_protocols
from ophyd import sim

var: bs_protocols.{type_} = sim.{hardware}
"""

    with tempfile.NamedTemporaryFile("wt") as f:
        f.write(template)
        f.seek(0)
        stdout, stderr, exit = mypy.api.run([f.name])
        # pass true means exit 0, pass false means nonzero exit
        try:
            assert exit != pass_
        except AssertionError:
            print(stdout)
            print(stderr)
            raise
