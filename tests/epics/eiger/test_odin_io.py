from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from ophyd_async.core import init_devices
from ophyd_async.epics.eiger._odin_io import (
    OdinFileWriterMX,  # noqa: PLC2701
    OdinWriting,  # noqa: PLC2701
)
from ophyd_async.testing import get_mock_put, set_mock_value

ODIN_DETECTOR_NAME = "odin_detector"


@pytest.fixture
def odin_file_writer(RE) -> OdinFileWriterMX:
    with init_devices(mock=True):
        writer = OdinFileWriterMX(MagicMock())
    return writer


async def test_when_open_called_then_file_correctly_set(
    odin_file_writer: OdinFileWriterMX, tmp_path: Path
):
    writer = odin_file_writer
    path_info = writer._path_provider.return_value  # type: ignore
    expected_filename = "filename.h5"
    path_info.directory_path = tmp_path
    path_info.filename = expected_filename

    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(writer.file_path).assert_called_once_with(str(tmp_path), wait=ANY)
    get_mock_put(writer.file_name).assert_called_once_with(expected_filename, wait=ANY)


async def test_when_open_called_then_all_expected_signals_set(
    odin_file_writer: OdinFileWriterMX,
):
    writer = odin_file_writer
    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(writer.data_type).assert_called_once_with("uint16", wait=ANY)
    get_mock_put(writer.num_capture).assert_called_once_with(
        0, wait=ANY
    )  # num_to_capture?

    get_mock_put(writer.capture).assert_called_once_with(OdinWriting.ON, wait=ANY)


async def test_given_data_shape_set_when_open_called_then_describe_has_correct_shape(
    odin_file_writer: OdinFileWriterMX,
):
    writer = odin_file_writer
    set_mock_value(writer.image_width, 1024)
    set_mock_value(writer.image_height, 768)
    description = await writer.open(ODIN_DETECTOR_NAME)
    assert description["data"]["shape"] == [1, 768, 1024]


async def test_when_closed_then_data_capture_turned_off(
    odin_file_writer: OdinFileWriterMX,
):
    writer = odin_file_writer
    await writer.close()
    get_mock_put(writer.capture).assert_called_once_with(OdinWriting.OFF, wait=ANY)
