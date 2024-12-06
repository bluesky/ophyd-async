from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from ophyd_async.core import DeviceCollector
from ophyd_async.epics.eiger._odin_io import Odin, OdinWriter, Writing  # noqa: PLC2701
from ophyd_async.testing import get_mock_put, set_mock_value

OdinDriverAndWriter = tuple[Odin, OdinWriter]


@pytest.fixture
def odin_driver_and_writer(RE) -> OdinDriverAndWriter:
    with DeviceCollector(mock=True):
        driver = Odin("")
        writer = OdinWriter(MagicMock(), lambda: "odin", driver)
    return driver, writer


async def test_when_open_called_then_file_correctly_set(
    odin_driver_and_writer: OdinDriverAndWriter, tmp_path: Path
):
    driver, writer = odin_driver_and_writer
    path_info = writer._path_provider.return_value
    expected_filename = "filename.h5"
    path_info.directory_path = tmp_path
    path_info.filename = expected_filename

    await writer.open()

    get_mock_put(driver.file_path).assert_called_once_with(str(tmp_path), wait=ANY)
    get_mock_put(driver.file_name).assert_called_once_with(expected_filename, wait=ANY)


async def test_when_open_called_then_all_expected_signals_set(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    await writer.open()

    get_mock_put(driver.data_type).assert_called_once_with("uint16", wait=ANY)
    get_mock_put(driver.num_to_capture).assert_called_once_with(0, wait=ANY)

    get_mock_put(driver.capture).assert_called_once_with(Writing.ON, wait=ANY)


async def test_given_data_shape_set_when_open_called_then_describe_has_correct_shape(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    set_mock_value(driver.image_width, 1024)
    set_mock_value(driver.image_height, 768)
    description = await writer.open()
    assert description["data"]["shape"] == [768, 1024]


async def test_when_closed_then_data_capture_turned_off(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    await writer.close()
    get_mock_put(driver.capture).assert_called_once_with(Writing.OFF, wait=ANY)
