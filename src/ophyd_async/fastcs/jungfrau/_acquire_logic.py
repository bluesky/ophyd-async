from ophyd_async.core import DEFAULT_TIMEOUT, DetectorAcquireLogic, wait_for_value

from ._io import DetectorStatus, JungfrauDriverIO, PedestalMode


class JungfrauAcquireLogic(DetectorAcquireLogic):
    def __init__(self, detector: JungfrauDriverIO) -> None:
        self.detector = detector

    async def start_acquiring(self):
        await self.detector.acquisition_start.trigger()

    async def wait_for_idle(self):
        await wait_for_value(
            self.detector.detector_status, DetectorStatus.IDLE, timeout=DEFAULT_TIMEOUT
        )

    async def ensure_stopped(self):
        await self.detector.acquisition_stop.trigger()
        await self.detector.pedestal_mode_state.set(PedestalMode.OFF)
