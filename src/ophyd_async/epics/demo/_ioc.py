import atexit
from pathlib import Path

from ophyd_async.epics.testing import TestingIOC

HERE = Path(__file__).absolute().parent


def start_ioc_subprocess(prefix: str, num_channels: int) -> TestingIOC:
    """Start an IOC subprocess for sample stage and sensor.

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
    # Start IOC and register it to be stopped at exit
    ioc.start()
    atexit.register(ioc.stop)
    return ioc
