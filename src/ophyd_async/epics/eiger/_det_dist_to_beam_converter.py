from enum import Enum

from numpy import interp, loadtxt


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
