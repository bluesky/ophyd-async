import asyncio
from enum import Enum
from typing import Sequence, Set

from ophyd_async.core import AsyncStatus, ShapeProvider
from ophyd_async.core.signal import set_and_wait_for_value

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


async def arm_and_trigger_detector_and_check_status_pv(
    driver: ADBase,
    good_states: Set[DetectorState] = DEFAULT_GOOD_STATES,
) -> AsyncStatus:
    status = await set_and_wait_for_value(driver.acquire, True)

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
