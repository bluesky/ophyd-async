import asyncio
from enum import Enum
from typing import Dict, FrozenSet, Optional, Sequence, Set, Type

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    ShapeProvider,
    set_and_wait_for_value,
)

from ...signal.signal import epics_signal_rw
from ..utils import ImageMode, ad_r, ad_rw
from ..writers.nd_plugin import NDArrayBase, NDPluginBase


class DetectorState(str, Enum):
    """
    Default set of states of an AreaDetector driver.
    See definition in ADApp/ADSrc/ADDriver.h in https://github.com/areaDetector/ADCore
    """

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


#: Default set of states that we should consider "good" i.e. the acquisition
#  is complete and went well
DEFAULT_GOOD_STATES: FrozenSet[DetectorState] = frozenset(
    [DetectorState.Idle, DetectorState.Aborted]
)


class ADBase(NDArrayBase):
    def __init__(
        self,
        prefix: str,
        name: str = "",
        enabled_plugins: Optional[Dict[str, Type[NDPluginBase]]] = None,
    ) -> None:
        self.enabled_plugins = {
            prefix: plugin_class(prefix) for prefix, plugin_class in enabled_plugins.values()
        } if enabled_plugins else {}
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
    good_states: Set[DetectorState] = set(DEFAULT_GOOD_STATES),
    timeout: float = DEFAULT_TIMEOUT,
) -> AsyncStatus:
    """
    Start acquiring driver, raising ValueError if the detector is in a bad state.

    This sets driver.acquire to True, and waits for it to be True up to a timeout.
    Then, it checks that the DetectorState PV is in DEFAULT_GOOD_STATES, and otherwise
    raises a ValueError.

    Parameters
    ----------
    driver:
        The driver to start acquiring. Must subclass ADBase.
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

    async def complete_acquisition() -> None:
        """NOTE: possible race condition here between the callback from
        set_and_wait_for_value and the detector state updating."""
        await status
        state = await driver.detector_state.get_value()
        if state not in good_states:
            raise ValueError(
                f"Final detector state {state} not in valid end states: {good_states}"
            )

    return AsyncStatus(complete_acquisition())


class ADBaseShapeProvider(ShapeProvider):
    def __init__(self, driver: ADBase) -> None:
        self._driver = driver

    async def __call__(self) -> Sequence[int]:
        shape = await asyncio.gather(
            self._driver.array_size_y.get_value(),
            self._driver.array_size_x.get_value(),
        )
        return shape
