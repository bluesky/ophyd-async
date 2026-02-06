from ophyd_async.core import AsyncReadable, StandardFlyer
from ophyd_async.sim import SimBlobDetector, SimMotor


async def test_readable():
    assert isinstance(SimMotor, AsyncReadable)
    assert isinstance(SimBlobDetector, AsyncReadable)
    assert not isinstance(StandardFlyer, AsyncReadable)
