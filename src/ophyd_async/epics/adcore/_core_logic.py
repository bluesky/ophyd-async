import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DatasetDescriber,
    DetectorController,
    set_and_wait_for_value,
)
from ophyd_async.epics.adcore._utils import convert_ad_dtype_to_np

from ._core_io import ADBaseIO, DetectorState

# Default set of states that we should consider "good" i.e. the acquisition
#  is complete and went well
DEFAULT_GOOD_STATES: frozenset[DetectorState] = frozenset(
    [DetectorState.Idle, DetectorState.Aborted]
)


class ADBaseDatasetDescriber(DatasetDescriber):
    def __init__(self, driver: ADBaseIO) -> None:
        self._driver = driver

    async def np_datatype(self) -> str:
        return convert_ad_dtype_to_np(await self._driver.data_type.get_value())

    async def shape(self) -> tuple[int, int]:
        shape = await asyncio.gather(
            self._driver.array_size_y.get_value(),
            self._driver.array_size_x.get_value(),
        )
        return shape


async def set_exposure_time_and_acquire_period_if_supplied(
    controller: DetectorController,
    driver: ADBaseIO,
    exposure: float | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """
    Sets the exposure time if it is not None and the acquire period to the
    exposure time plus the deadtime. This is expected behavior for most
    AreaDetectors, but some may require more specialized handling.

    Parameters
    ----------
    controller:
        Controller that can supply a deadtime.
    driver:
        The driver to start acquiring. Must subclass ADBaseIO.
    exposure:
        Desired exposure time, this is a noop if it is None.
    timeout:
        How long to wait for the exposure time and acquire period to be set.
    """
    if exposure is not None:
        full_frame_time = exposure + controller.get_deadtime(exposure)
        await asyncio.gather(
            driver.acquire_time.set(exposure, timeout=timeout),
            driver.acquire_period.set(full_frame_time, timeout=timeout),
        )


async def start_acquiring_driver_and_ensure_status(
    driver: ADBaseIO,
    good_states: frozenset[DetectorState] = frozenset(DEFAULT_GOOD_STATES),
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
        The driver to start acquiring. Must subclass ADBaseIO.
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
