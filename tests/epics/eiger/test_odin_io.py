from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest

from ophyd_async.core import DEFAULT_TIMEOUT, init_devices
from ophyd_async.epics.eiger import Odin, OdinWriter, Writing
from ophyd_async.testing import get_mock_put, set_mock_value

ODIN_DETECTOR_NAME = "odin_detector"
EIGER_BIT_DEPTH = 16

OdinDriverAndWriter = tuple[Odin, OdinWriter]


@pytest.fixture
def odin_driver_and_writer(RE) -> OdinDriverAndWriter:
    eiger_bit_depth = AsyncMock(get_value=AsyncMock(return_value=EIGER_BIT_DEPTH))
    with init_devices(mock=True):
        driver = Odin("")
        writer = OdinWriter(MagicMock(), driver, eiger_bit_depth)

    # Set meta and capturing pvs high
    set_mock_value(driver.meta_active, "Active")
    set_mock_value(driver.capture_rbv, "Capturing")
    set_mock_value(driver.meta_writing, "Writing")
    return driver, writer


async def test_when_open_called_then_file_correctly_set(
    odin_driver_and_writer: OdinDriverAndWriter, tmp_path: Path
):
    driver, writer = odin_driver_and_writer
    path_info = writer._path_provider.return_value  # type: ignore
    expected_filename = "filename.h5"
    path_info.directory_path = tmp_path
    path_info.filename = expected_filename

    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(driver.file_path).assert_called_once_with(str(tmp_path), wait=ANY)
    get_mock_put(driver.file_name).assert_called_once_with(expected_filename, wait=ANY)


async def test_when_open_called_then_all_expected_signals_set(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer

    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(driver.data_type).assert_called_once_with("UInt16", wait=ANY)
    get_mock_put(driver.num_to_capture).assert_called_once_with(0, wait=ANY)

    get_mock_put(driver.capture).assert_called_once_with(Writing.CAPTURE, wait=ANY)


async def test_bit_depth_is_passed_before_open_and_set_to_data_type_after_open(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer

    assert await writer._eiger_bit_depth().get_value() == EIGER_BIT_DEPTH
    assert await driver.data_type.get_value() == ""
    await writer.open(ODIN_DETECTOR_NAME)
    get_mock_put(driver.data_type).assert_called_once_with(
        f"UInt{EIGER_BIT_DEPTH}", wait=ANY
    )


async def test_given_data_shape_set_when_open_called_then_describe_has_correct_shape(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    set_mock_value(driver.image_width, 1024)
    set_mock_value(driver.image_height, 768)
    description = await writer.open(ODIN_DETECTOR_NAME)
    assert description["data"]["shape"] == [1, 768, 1024]


async def test_when_closed_then_data_capture_turned_off(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    await writer.close()
    get_mock_put(driver.capture).assert_called_once_with(Writing.DONE, wait=ANY)


@pytest.mark.asyncio
@patch("ophyd_async.epics.eiger._odin_io.wait_for_value")
async def test_wait_for_active_before_capture_then_wait_for_writing(
    mock_wait_for_value,
    odin_driver_and_writer,
):
    driver, writer = odin_driver_and_writer
    writer._drv.capture.set = AsyncMock()

    mock_manager = AsyncMock()
    mock_manager.attach_mock(mock_wait_for_value, "mock_wait_for_value")
    mock_manager.attach_mock(writer._drv.capture.set, "mock_capture_set")

    await writer.open(ODIN_DETECTOR_NAME)

    expected_calls = [
        call.mock_wait_for_value(driver.meta_active, "Active", timeout=DEFAULT_TIMEOUT),
        call.mock_capture_set(Writing.CAPTURE, wait=False),
        call.mock_wait_for_value(
            driver.capture_rbv, "Capturing", timeout=DEFAULT_TIMEOUT
        ),
        call.mock_wait_for_value(
            driver.meta_writing, "Writing", timeout=DEFAULT_TIMEOUT
        ),
    ]

    assert mock_manager.mock_calls == expected_calls
