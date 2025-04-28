from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from ophyd_async.core import init_devices
from ophyd_async.fastcs.odin import OdinHdfIO, OdinWriter, OdinWriting
from ophyd_async.testing import get_mock_put, set_mock_value

OdinDriverAndWriter = tuple[OdinHdfIO, OdinWriter]


@pytest.fixture
def odin_driver_and_writer(RE) -> OdinDriverAndWriter:
    with init_devices(mock=True):
        driver = OdinHdfIO("")
        writer = OdinWriter(MagicMock(), driver)
    return driver, writer


async def test_when_open_called_then_file_correctly_set(
    odin_driver_and_writer: OdinDriverAndWriter, tmp_path: Path
):
    driver, writer = odin_driver_and_writer
    path_info = writer._path_provider.return_value  # type: ignore
    expected_filename = "filename.h5"
    path_info.directory_path = tmp_path
    path_info.filename = expected_filename

    await writer.open("Odin")

    get_mock_put(driver.file_path).assert_called_once_with(str(tmp_path), wait=ANY)
    get_mock_put(driver.file_prefix).assert_called_once_with(
        expected_filename, wait=ANY
    )


async def test_when_open_called_then_all_expected_signals_set(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    await writer.open("Odin")

    get_mock_put(driver.data_datatype).assert_called_once_with("UInt16", wait=ANY)
    get_mock_put(driver.frames).assert_called_once_with(0, wait=ANY)

    get_mock_put(driver.config_hdf_write).assert_called_once_with(
        OdinWriting.ON, wait=ANY
    )


async def test_given_data_shape_set_when_open_called_then_describe_has_correct_shape(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    set_mock_value(driver.data_dims_1, 1024)
    set_mock_value(driver.data_dims_0, 768)
    description = await writer.open("Odin")
    assert description["data"]["shape"] == [768, 1024]


async def test_when_closed_then_data_capture_turned_off(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer

    await writer.close()
    get_mock_put(driver.config_hdf_write).assert_called_once_with(
        OdinWriting.OFF, wait=ANY
    )
