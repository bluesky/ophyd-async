import asyncio
from asyncio import Event
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from ophyd_async.core import init_devices
from ophyd_async.epics.eiger import Odin, OdinWriter, Writing
from ophyd_async.testing import (
    callback_on_mock_put,
    get_mock_put,
    set_mock_value,
)

ODIN_DETECTOR_NAME = "odin_detector"
EIGER_BIT_DEPTH = 16

OdinDriverAndWriter = tuple[Odin, OdinWriter]


@pytest.fixture
def odin_driver_and_writer(RE) -> OdinDriverAndWriter:
    eiger_bit_depth = AsyncMock(get_value=AsyncMock(return_value=EIGER_BIT_DEPTH))
    with init_devices(mock=True):
        driver = Odin("")
        writer = OdinWriter(MagicMock(), driver, eiger_bit_depth)
    writer._path_provider.return_value.filename = "filename.h5"  # type: ignore
    return driver, writer


def initialise_signals_to_armed(driver):
    set_mock_value(driver.meta_active, "Active")
    set_mock_value(driver.capture_rbv, "Capturing")
    set_mock_value(driver.meta_writing, "Writing")
    set_mock_value(driver.meta_file_name, "filename.h5")
    set_mock_value(driver.id, "filename.h5")


async def test_when_open_called_then_file_correctly_set(
    odin_driver_and_writer: OdinDriverAndWriter, tmp_path: Path
):
    driver, writer = odin_driver_and_writer
    initialise_signals_to_armed(driver)
    path_info = writer._path_provider.return_value  # type: ignore
    path_info.directory_path = tmp_path
    expected_filename = "filename.h5"

    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(driver.file_path).assert_called_once_with(str(tmp_path), wait=ANY)
    get_mock_put(driver.file_name).assert_called_once_with(expected_filename, wait=ANY)


async def test_when_open_called_then_all_expected_signals_set(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    initialise_signals_to_armed(driver)

    await writer.open(ODIN_DETECTOR_NAME)

    get_mock_put(driver.data_type).assert_called_once_with("UInt16", wait=ANY)
    get_mock_put(driver.num_to_capture).assert_called_once_with(0, wait=ANY)

    get_mock_put(driver.capture).assert_called_once_with(Writing.CAPTURE, wait=ANY)


async def test_bit_depth_is_passed_before_open_and_set_to_data_type_after_open(
    odin_driver_and_writer: OdinDriverAndWriter,
):
    driver, writer = odin_driver_and_writer
    initialise_signals_to_armed(driver)

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
    initialise_signals_to_armed(driver)

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
async def test_wait_for_active_and_file_names_before_capture_then_wait_for_writing(
    odin_driver_and_writer,
):
    driver, writer = odin_driver_and_writer

    file_name_is_set = Event()
    capture_is_set = Event()
    callback_on_mock_put(
        driver.file_name, lambda *args, **kwargs: file_name_is_set.set()
    )
    callback_on_mock_put(driver.capture, lambda *args, **kwargs: capture_is_set.set())

    async def set_waited_signals():
        set_mock_value(driver.meta_active, "Active")
        set_mock_value(driver.id, "filename.h5")
        set_mock_value(driver.meta_file_name, "filename.h5")

    async def set_ready_signals():
        set_mock_value(driver.meta_writing, "Writing")
        set_mock_value(driver.capture_rbv, "Capturing")

    async def wait_and_set_signals():
        # Block until filename is set
        await file_name_is_set.wait()
        # Allow writer.open to proceed to wait_for_value.
        await asyncio.sleep(0.1)
        # writer.open now waits on signals; set these, and unset event
        await set_waited_signals()
        # Block until capture sets event
        await capture_is_set.wait()
        # Allow writer.open to proceed to wait_for_value.
        await asyncio.sleep(0.1)
        # writer.open now waits on signals; set these
        await set_ready_signals()

    await asyncio.gather(writer.open(ODIN_DETECTOR_NAME), wait_and_set_signals())
