from collections.abc import Sequence
from pathlib import Path

from ophyd_async.epics.testing import DEFAULT_SOFTIOC_ARGS, TestingIOC

HERE = Path(__file__).absolute().parent


def demo_ioc_args(
    prefix: str,
    num_channels: int,
    softioc_args: Sequence[str] = DEFAULT_SOFTIOC_ARGS,
) -> list[str]:
    """Build the argv for an IOC serving a sample stage and sensor.

    Doesn't start anything - pass the result to
    `ophyd_async.epics.testing.start_ioc`.

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
    :param softioc_args: Argv prefix used to host the IOC, defaulting to the
        bundled `epicscorelibs.ioc`. Override to run against a real EPICS
        installation's `softIoc` binary instead, e.g. `["softIoc"]`.
    """
    ioc = TestingIOC()
    # Create X and Y motors
    for suffix in ["X", "Y"]:
        ioc.add_database(HERE / "motor.db", P=f"{prefix}STAGE:{suffix}:")
    # Create a multichannel counter with num_counters
    ioc.add_database(HERE / "point_detector.db", P=f"{prefix}DET:")
    for i in range(1, num_channels + 1):
        ioc.add_database(
            HERE / "point_detector_channel.db",
            P=f"{prefix}DET:",
            CHANNEL=str(i),
            X=f"{prefix}STAGE:X:",
            Y=f"{prefix}STAGE:Y:",
        )
    return ioc.args(softioc_args)
