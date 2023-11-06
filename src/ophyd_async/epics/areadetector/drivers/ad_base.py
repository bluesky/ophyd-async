import asyncio
from enum import Enum
from typing import Sequence, Set

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    ShapeProvider,
    set_and_wait_for_value,
)

from ...signal.signal import epics_signal_rw
from ..utils import ImageMode, ad_r, ad_rw
from ..writers.nd_plugin import NDArrayBase


class DetectorState(str, Enum):
    Idle = "Idle"
    Acquire = "Acquire"
    Readout = "Readout"
    Correct = "Correct"
    Saving = "Saving"
    Aborting = "Aborting"
    Error = "Error"
    Waiting = "Waiting"
    Initializing = "Initializing"
    Disconnected = "Disconnected"
    Aborted = "Aborted"


DEFAULT_GOOD_STATES: Set[DetectorState] = set([DetectorState.Idle])


class ADBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        # Define some signals
        self.acquire = ad_rw(bool, prefix + "Acquire")
        self.acquire_time = ad_rw(float, prefix + "AcquireTime")
        self.num_images = ad_rw(int, prefix + "NumImages")
        self.image_mode = ad_rw(ImageMode, prefix + "ImageMode")
        self.array_counter = ad_rw(int, prefix + "ArrayCounter")
        self.array_size_x = ad_r(int, prefix + "ArraySizeX")
        self.array_size_y = ad_r(int, prefix + "ArraySizeY")
        self.detector_state = ad_r(DetectorState, prefix + "DetectorState")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")
        super().__init__(prefix, name=name)


async def start_acquiring_driver_and_ensure_status(
    driver: ADBase,
    good_states: Set[DetectorState] = DEFAULT_GOOD_STATES,
    timeout: float = DEFAULT_TIMEOUT,
) -> AsyncStatus:
    """Start aquiring driver, raising ValueError if the detector is in a bad state.

    This sets driver.acquire to True, and waits for it to be True up to a timeout.
    Then, it checks that the DetectorState PV is in DEFAULT_GOOD_STATES, and otherwise
    raises a ValueError.

    Parameters
    ----------
    driver:
        The driver to start aquiring. Must subclass ADBase.
    good_states:
        set of states defined in DetectorState enum which are considered good states.
    timeout:
        How long to wait for driver.acquire to readback True (i.e. acquiring).

    Returns
    -------
    AsyncStatus:
        An AsyncStatus that can be awaited to set driver.acquire to True and perform
        subsequent raising (if applicable) due to detector state.
    """

    status = await set_and_wait_for_value(driver.acquire, True, timeout=timeout)

    async def completion_task() -> None:
        await status
        state = await driver.detector_state.get_value()
        if state not in good_states:
            raise ValueError(
                f"Final detector state {state} not in valid end states: {good_states}"
            )

    return AsyncStatus(completion_task())


class ADBaseShapeProvider(ShapeProvider):
    def __init__(self, driver: ADBase) -> None:
        self._driver = driver

    async def __call__(self) -> Sequence[int]:
        shape = await asyncio.gather(
            self._driver.array_size_y.get_value(),
            self._driver.array_size_x.get_value(),
        )
        return shape
