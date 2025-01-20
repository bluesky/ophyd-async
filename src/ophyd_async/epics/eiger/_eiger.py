from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from numpy import interp, loadtxt
from pydantic import Field

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO
from ._odin_io import Odin, OdinWriter

ALL_DETECTORS: dict[str, "DetectorSizeConstants"] = {}
T = TypeVar("T", bound=float | int)
EIGER_TYPE_EIGER2_X_16M = "EIGER2_X_16M"


@dataclass
class EigerTimeouts:
    stale_params_timeout: int = 60
    general_status_timeout: int = 10
    meta_file_ready_timeout: int = 30
    all_frames_timeout: int = 120
    arming_timeout: int = 60


@dataclass
class DetectorSize(Generic[T]):
    width: T
    height: T


@dataclass
class DetectorSizeConstants:
    det_type_string: str
    det_dimension: DetectorSize[float]
    det_size_pixels: DetectorSize[int]
    roi_dimension: DetectorSize[float]
    roi_size_pixels: DetectorSize[int]

    def __post_init__(self):
        ALL_DETECTORS[self.det_type_string] = self


EIGER_TYPE_EIGER2_X_4M = "EIGER2_X_4M"
EIGER2_X_4M_DIMENSION_X = 155.1
EIGER2_X_4M_DIMENSION_Y = 162.15
EIGER2_X_4M_DIMENSION = DetectorSize(EIGER2_X_4M_DIMENSION_X, EIGER2_X_4M_DIMENSION_Y)
PIXELS_X_EIGER2_X_4M = 2068
PIXELS_Y_EIGER2_X_4M = 2162
PIXELS_EIGER2_X_4M = DetectorSize(PIXELS_X_EIGER2_X_4M, PIXELS_Y_EIGER2_X_4M)
EIGER2_X_4M_SIZE = DetectorSizeConstants(
    EIGER_TYPE_EIGER2_X_4M,
    EIGER2_X_4M_DIMENSION,
    PIXELS_EIGER2_X_4M,
    EIGER2_X_4M_DIMENSION,
    PIXELS_EIGER2_X_4M,
)

EIGER_TYPE_EIGER2_X_9M = "EIGER2_X_9M"
EIGER2_X_9M_DIMENSION_X = 233.1
EIGER2_X_9M_DIMENSION_Y = 244.65
EIGER2_X_9M_DIMENSION = DetectorSize(EIGER2_X_9M_DIMENSION_X, EIGER2_X_9M_DIMENSION_Y)
PIXELS_X_EIGER2_X_9M = 3108
PIXELS_Y_EIGER2_X_9M = 3262
PIXELS_EIGER2_X_9M = DetectorSize(PIXELS_X_EIGER2_X_9M, PIXELS_Y_EIGER2_X_9M)
EIGER2_X_9M_SIZE = DetectorSizeConstants(
    EIGER_TYPE_EIGER2_X_9M,
    EIGER2_X_9M_DIMENSION,
    PIXELS_EIGER2_X_9M,
    EIGER2_X_9M_DIMENSION,
    PIXELS_EIGER2_X_9M,
)

EIGER_TYPE_EIGER2_X_16M = "EIGER2_X_16M"
EIGER2_X_16M_DIMENSION_X = 311.1
EIGER2_X_16M_DIMENSION_Y = 327.15
EIGER2_X_16M_DIMENSION = DetectorSize(
    EIGER2_X_16M_DIMENSION_X, EIGER2_X_16M_DIMENSION_Y
)
PIXELS_X_EIGER2_X_16M = 4148
PIXELS_Y_EIGER2_X_16M = 4362
PIXELS_EIGER2_X_16M = DetectorSize(PIXELS_X_EIGER2_X_16M, PIXELS_Y_EIGER2_X_16M)
EIGER2_X_16M_SIZE = DetectorSizeConstants(
    EIGER_TYPE_EIGER2_X_16M,
    EIGER2_X_16M_DIMENSION,
    PIXELS_EIGER2_X_16M,
    EIGER2_X_4M_DIMENSION,
    PIXELS_EIGER2_X_4M,
)


class Axis(Enum):
    X_AXIS = 1
    Y_AXIS = 2


class DetectorDistanceToBeamXYConverter:
    def __init__(self, lookup_file: str):
        self.lookup_file: str = lookup_file
        self.lookup_table_values: list = self.parse_table()

    def get_beam_xy_from_det_dist(self, det_dist_mm: float, beam_axis: Axis) -> float:
        beam_axis_values = self.lookup_table_values[beam_axis.value]
        det_dist_array = self.lookup_table_values[0]
        return float(interp(det_dist_mm, det_dist_array, beam_axis_values))

    def get_beam_axis_pixels(
        self,
        det_distance: float,
        image_size_pixels: int,
        det_dim: float,
        beam_axis: Axis,
    ) -> float:
        beam_mm = self.get_beam_xy_from_det_dist(det_distance, beam_axis)
        return beam_mm * image_size_pixels / det_dim

    def get_beam_y_pixels(
        self, det_distance: float, image_size_pixels: int, det_dim: float
    ) -> float:
        return self.get_beam_axis_pixels(
            det_distance, image_size_pixels, det_dim, Axis.Y_AXIS
        )

    def get_beam_x_pixels(
        self, det_distance: float, image_size_pixels: int, det_dim: float
    ) -> float:
        return self.get_beam_axis_pixels(
            det_distance, image_size_pixels, det_dim, Axis.X_AXIS
        )

    def reload_lookup_table(self):
        self.lookup_table_values = self.parse_table()

    def parse_table(self) -> list:
        rows = loadtxt(self.lookup_file, delimiter=" ", comments=["#", "Units"])
        columns = list(zip(*rows, strict=False))

        return columns

    def __eq__(self, other):
        if not isinstance(other, DetectorDistanceToBeamXYConverter):
            return NotImplemented
        if self.lookup_file != other.lookup_file:
            return False
        if self.lookup_table_values != other.lookup_table_values:
            return False
        return True


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
