import atexit
from pathlib import Path

from ophyd_async.epics.testing import TestingIOC

HERE = Path(__file__).absolute().parent


def start_ioc_subprocess(prefix: str, num_counters: int):
    """Start an IOC subprocess with EPICS database for sample stage and sensor
    with the same pv prefix
    """
    ioc = TestingIOC()
    # Create X and Y motors
    for suffix in ["X", "Y"]:
        ioc.add_database(HERE / "mover.db", P=f"{prefix}STAGE:{suffix}:")
    # Create a multichannel counter with num_counters
    ioc.add_database(HERE / "multichannelcounter.db", P=f"{prefix}MCC:")
    for i in range(1, num_counters + 1):
        ioc.add_database(
            HERE / "counter.db",
            P=f"{prefix}MCC:",
            CHANNEL=str(i),
            X=f"{prefix}STAGE:X:",
            Y=f"{prefix}STAGE:Y:",
        )
    # Start IOC and register it to be stopped at exit
    ioc.start()
    atexit.register(ioc.stop)
