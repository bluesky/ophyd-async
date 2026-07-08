from pathlib import Path

from ophyd_async.epics.testing import SubprocessSpec, TestingIOC

HERE = Path(__file__).absolute().parent


def ioc_subprocess_spec(prefix: str, num_channels: int) -> SubprocessSpec:
    """Build the subprocess spec for an IOC serving a sample stage and sensor.

    Doesn't start anything - pass the result to `ophyd_async.testing.start_subprocess`.

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
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
    return ioc.spec()
