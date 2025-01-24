from unittest.mock import Mock, patch

import pytest

from ophyd_async.epics.eiger.det_dist_to_beam_converter import (
    Axis,
    DetectorDistanceToBeamXYConverter,
)

LOOKUP_TABLE_TEST_VALUES = [(100.0, 200.0), (150.0, 151.0), (160.0, 165.0)]


@pytest.fixture
def fake_converter():
    with patch.object(
        DetectorDistanceToBeamXYConverter,
        "parse_table",
        return_value=LOOKUP_TABLE_TEST_VALUES,
    ):
        yield DetectorDistanceToBeamXYConverter("test.txt")


def test_converter_eq():
    test_file = "tests/epics/eiger/test_lookup_table.txt"
    test_converter = DetectorDistanceToBeamXYConverter(test_file)
    test_converter_dupe = DetectorDistanceToBeamXYConverter(test_file)
    test_file_2 = "tests/epics/eiger/test_lookup_table_2.txt"
    test_converter_2 = DetectorDistanceToBeamXYConverter(test_file_2)
    assert test_converter != 1
    assert test_converter == test_converter_dupe
    assert test_converter != test_converter_2
    previous_value = test_converter_dupe.lookup_table_values[0]
    test_converter_dupe.lookup_table_values[0] = (7.5, 23.5)
    assert test_converter != test_converter_dupe
    test_converter_dupe.lookup_table_values[0] = previous_value


@pytest.mark.parametrize(
    "detector_distance, axis, expected_value",
    [
        (100.0, Axis.Y_AXIS, 160.0),
        (200.0, Axis.X_AXIS, 151.0),
        (150.0, Axis.X_AXIS, 150.5),
        (190.0, Axis.Y_AXIS, 164.5),
    ],
)
def test_interpolate_beam_xy_from_det_distance(
    fake_converter: DetectorDistanceToBeamXYConverter,
    detector_distance: float,
    axis: Axis,
    expected_value: float,
):
    assert isinstance(
        fake_converter.get_beam_xy_from_det_dist(detector_distance, axis), float
    )

    assert (
        fake_converter.get_beam_xy_from_det_dist(detector_distance, axis)
        == expected_value
    )


def test_get_beam_in_pixels(fake_converter: DetectorDistanceToBeamXYConverter):
    detector_distance = 100.0
    image_size_pixels = 100
    detector_dimensions = 200.0
    interpolated_x_value = 150.0
    interpolated_y_value = 160.0

    def mock_callback(dist: float, axis: Axis):
        match axis:
            case Axis.X_AXIS:
                return interpolated_x_value
            case Axis.Y_AXIS:
                return interpolated_y_value

    fake_converter.get_beam_xy_from_det_dist = Mock()
    fake_converter.get_beam_xy_from_det_dist.side_effect = mock_callback
    expected_y_value = interpolated_y_value * image_size_pixels / detector_dimensions
    expected_x_value = interpolated_x_value * image_size_pixels / detector_dimensions

    calculated_y_value = fake_converter.get_beam_y_pixels(
        detector_distance, image_size_pixels, detector_dimensions
    )

    assert calculated_y_value == expected_y_value
    assert (
        fake_converter.get_beam_x_pixels(
            detector_distance, image_size_pixels, detector_dimensions
        )
        == expected_x_value
    )


def test_parse_table():
    test_file = "tests/epics/eiger/test_lookup_table.txt"
    test_converter = DetectorDistanceToBeamXYConverter(test_file)

    assert test_converter.lookup_file == test_file
    assert test_converter.lookup_table_values == LOOKUP_TABLE_TEST_VALUES
    assert test_converter.parse_table() == LOOKUP_TABLE_TEST_VALUES

    test_converter.reload_lookup_table()

    assert test_converter.lookup_file == test_file
    assert test_converter.lookup_table_values == LOOKUP_TABLE_TEST_VALUES
