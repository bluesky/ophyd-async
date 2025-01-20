from dataclasses import dataclass

from pydantic import Field

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo

from ._det_dim_constants import (
    EIGER2_X_16M_SIZE,
    DetectorSize,
    DetectorSizeConstants,
)
from ._det_dist_to_beam_converter import (
    DetectorDistanceToBeamXYConverter,
)
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
    detector_size_constants: DetectorSizeConstants = EIGER2_X_16M_SIZE
    use_roi_mode: bool
    det_dist_to_beam_converter_path: str
    detector_distance: float
    omega_start: float
    omega_increment: float

    @property
    def beam_xy_converter(self) -> DetectorDistanceToBeamXYConverter:
        return DetectorDistanceToBeamXYConverter(self.det_dist_to_beam_converter_path)

    def get_detector_size_pizels(self) -> DetectorSize:
        full_size = self.detector_size_constants.det_size_pixels
        roi_size = self.detector_size_constants.roi_size_pixels
        return roi_size if self.use_roi_mode else full_size

    def get_beam_position_pixels(self, detector_distance: float) -> tuple[float, float]:
        full_size_pixels = self.detector_size_constants.det_size_pixels
        roi_size_pixels = self.get_detector_size_pizels()

        x_beam_pixels = self.beam_xy_converter.get_beam_x_pixels(
            detector_distance,
            full_size_pixels.width,
            self.detector_size_constants.det_dimension.width,
        )
        y_beam_pixels = self.beam_xy_converter.get_beam_y_pixels(
            detector_distance,
            full_size_pixels.height,
            self.detector_size_constants.det_dimension.height,
        )

        offset_x = (full_size_pixels.width - roi_size_pixels.width) / 2.0
        offset_y = (full_size_pixels.height - roi_size_pixels.height) / 2.0

        return x_beam_pixels - offset_x, y_beam_pixels - offset_y


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
    async def set_mx_settings_pvs(self) -> None:
        if not self.detector_params:
            raise TypeError("Detector parameters are not instantiated")
        beam_x_pixels, beam_y_pixels = self.detector_params.get_beam_position_pixels(
            self.detector_params.detector_distance
        )
        self.drv.beam_centre_x.set(
            beam_x_pixels, timeout=self.timeouts.general_status_timeout
        )
        self.drv.beam_centre_y.set(
            beam_y_pixels, timeout=self.timeouts.general_status_timeout
        )
        self.drv.det_distance.set(
            self.detector_params.detector_distance,
            timeout=self.timeouts.general_status_timeout,
        )
        self.drv.omega_start.set(
            self.detector_params.omega_start,
            timeout=self.timeouts.general_status_timeout,
        )
        self.drv.omega_increment.set(
            self.detector_params.omega_increment,
            timeout=self.timeouts.general_status_timeout,
        )
