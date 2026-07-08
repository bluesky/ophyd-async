import subprocess
import sys
from pathlib import Path

from ophyd_async.epics.testing import DEFAULT_SOFTIOC_ARGS, Database, ioc_argv

HERE = Path(__file__).absolute().parent


def demo_ioc_database(prefix: str, num_channels: int) -> list[Database]:
    """Build the `Database`s for an IOC serving a sample stage and sensor.

    Doesn't start anything - pass the result to
    `ophyd_async.epics.testing.start_ioc` (which is where you can override
    which executable actually hosts the IOC).

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
    """
    databases = [
        # Create X and Y motors
        Database(HERE / "motor.db", {"P": f"{prefix}STAGE:{suffix}:"})
        for suffix in ["X", "Y"]
    ]
    # Create a multichannel counter with num_channels
    databases.append(Database(HERE / "point_detector.db", {"P": f"{prefix}DET:"}))
    databases += [
        Database(
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
    return databases


if __name__ == "__main__":
    # Convenience standalone entry point: `python _ioc.py <prefix> <num_channels>
    # [softioc_args...]` builds and hosts the demo topology directly, without
    # needing to write any Python. Trailing args override which executable
    # actually hosts the IOC, defaulting to DEFAULT_SOFTIOC_ARGS - e.g.
    # `python _ioc.py demo: 3 softIoc` to use a real EPICS installation instead
    # of the bundled epicscorelibs.ioc.
    if len(sys.argv) < 3:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <prefix> <num_channels> [softioc_args...]"
        )
    _prefix, _num_channels, *_softioc_args = sys.argv[1:]
    _databases = demo_ioc_database(_prefix, int(_num_channels))
    sys.exit(
        subprocess.run(
            [*(_softioc_args or DEFAULT_SOFTIOC_ARGS), *ioc_argv(_databases)]
        ).returncode
    )
