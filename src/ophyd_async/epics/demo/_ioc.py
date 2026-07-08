from pathlib import Path

from ophyd_async.epics.testing import ioc_args

HERE = Path(__file__).absolute().parent


def demo_ioc_args(prefix: str, num_channels: int) -> list[str]:
    """Build the `-m macro -d db` argv for an IOC serving a sample stage and sensor.

    Doesn't start anything - pass the result to
    `ophyd_async.epics.testing.start_ioc` (which is where you can override which
    executable actually hosts the IOC).

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
    """
    databases: list[tuple[Path, dict[str, str]]] = [
        # Create X and Y motors
        (HERE / "motor.db", {"P": f"{prefix}STAGE:{suffix}:"})
        for suffix in ["X", "Y"]
    ]
    # Create a multichannel counter with num_channels
    databases.append((HERE / "point_detector.db", {"P": f"{prefix}DET:"}))
    databases += [
        (
            HERE / "point_detector_channel.db",
            {
                "P": f"{prefix}DET:",
                "CHANNEL": str(i),
                "X": f"{prefix}STAGE:X:",
                "Y": f"{prefix}STAGE:Y:",
            },
        )
        for i in range(1, num_channels + 1)
    ]
    return ioc_args(databases)
