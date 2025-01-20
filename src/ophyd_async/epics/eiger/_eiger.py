from dataclasses import dataclass

from pydantic import Field

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO
from ._odin_io import Odin, OdinWriter


@dataclass
class EigerTimeouts:
    stale_params_timeout: int = 60
    general_status_timeout: int = 10
    meta_file_ready_timeout: int = 30
    all_frames_timeout: int = 120
    arming_timeout: int = 60


class EigerTriggerInfo(TriggerInfo):
    energy_ev: float = Field(gt=0)
    exposure_time: float = Field()


class EigerDetector(StandardDetector):
    """
    Ophyd-async implementation of an Eiger Detector.
    """

    _controller: EigerController
    _writer: OdinWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-01:",
        hdf_suffix="-EA-ODIN-01:",
        name="",
    ):
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = Odin(prefix + hdf_suffix + "FP:")
        self.detector_params: EigerTriggerInfo | None = None
        self.timeouts = EigerTimeouts()
        super().__init__(
            EigerController(self.drv),
            OdinWriter(path_provider, lambda: self.name, self.odin),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: EigerTriggerInfo) -> None:  # type: ignore
        await self._controller.set_energy(value.energy_ev)
        await super().prepare(value)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        assert self.detector_params
        detector_params: EigerTriggerInfo = self.detector_params
        await self._writer.close()
        await self.set_detector_threshold(detector_params.energy_ev)
        await self.set_cam_pvs()

    @AsyncStatus.wrap
    async def set_detector_threshold(self, energy: float, tolerance: float = 0.1):
        current_energy = await self.drv.photon_energy.get_value()
        if abs(current_energy - energy) > tolerance:
            return self.drv.photon_energy.set(
                energy, timeout=self.timeouts.general_status_timeout
            )

    @AsyncStatus.wrap
    async def set_cam_pvs(self):
        assert self.detector_params
        await self.drv.acquire_time.set(
            self.detector_params.exposure_time,
            timeout=self.timeouts.general_status_timeout,
        )
        await self.drv.acquire_period.set(
            self.detector_params.exposure_time,
            timeout=self.timeouts.general_status_timeout,
        )
        await self.drv.num_exposures.set(
            1, timeout=self.timeouts.general_status_timeout
        )
        # await self.drv.image_mode.set(
        #     self.cam.ImageMode.MULTIPLE, timeout=self.timeouts.general_status_timeout
        # )
        # await self.drv.trigger_mode.set(
        #     InternalEigerTriggerMode.EXTERNAL_SERIES.value,
        #     timeout=self.timeouts.general_status_timeout,
        # )

    @AsyncStatus.wrap
    async def set_odin_number_of_frame_chunks(self):
        # assert self.detector_params is not None
        # self._writer.num_frames_chunks.set(
        #     1, timeout=self.timeouts.general_status_timeout
        # )
        pass
