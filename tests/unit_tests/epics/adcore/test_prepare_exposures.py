from unittest.mock import call

import pytest

from ophyd_async.core import get_mock, init_devices
from ophyd_async.epics import adcore


@pytest.fixture
async def adbase():
    async with init_devices(mock=True):
        adbase = adcore.ADBaseIO("PREFIX:ADBASE:")
    return adbase


@pytest.fixture
async def process_plugin():
    async with init_devices(mock=True):
        process = adcore.NDProcessIO("PREFIX:PROC:")
    return process


@pytest.mark.parametrize(
    "num,livetime,deadtime,expected_calls",
    [
        # Single exposure with default livetime and deadtime
        (
            1,
            0.0,
            0.0,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(1),
            ],
        ),
        # Multiple exposures with no livetime or deadtime
        (
            5,
            0.0,
            0.0,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(5),
            ],
        ),
        # Continuous mode (num=0)
        (
            0,
            0.0,
            0.0,
            [
                call.image_mode.put(adcore.ADImageMode.CONTINUOUS),
                call.num_images.put(0),
            ],
        ),
        # With livetime only
        (
            5,
            0.1,
            0.0,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(5),
                call.acquire_time.put(0.1),
            ],
        ),
        # With livetime and deadtime
        (
            10,
            0.2,
            0.05,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(10),
                call.acquire_time.put(0.2),
                call.acquire_period.put(0.25),
            ],
        ),
        # Large number of exposures with livetime only
        (
            100,
            0.01,
            0.0,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(100),
                call.acquire_time.put(0.01),
            ],
        ),
        # With deadtime but no livetime (deadtime should be ignored)
        (
            5,
            0.0,
            0.1,
            [
                call.image_mode.put(adcore.ADImageMode.MULTIPLE),
                call.num_images.put(5),
            ],
        ),
    ],
)
async def test_prepare_exposures(
    adbase: adcore.ADBaseIO, num, livetime, deadtime, expected_calls
):
    await adcore.prepare_exposures(
        adbase, num=num, livetime=livetime, deadtime=deadtime
    )
    assert get_mock(adbase).mock_calls == expected_calls


@pytest.mark.parametrize(
    "exposures_per_collection,filter_type,expected_calls",
    [
        # Default filter type (AVERAGE) with 1 exposure
        (
            1,
            adcore.NDProcessFilterType.AVERAGE,
            [
                call.num_filter.put(1),
                call.enable_filter.put(True),
                call.filter_type.put(adcore.NDProcessFilterType.AVERAGE),
                call.auto_reset_filter.put(True),
                call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
                call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
            ],
        ),
        # Multiple exposures with default AVERAGE filter
        (
            5,
            adcore.NDProcessFilterType.AVERAGE,
            [
                call.num_filter.put(5),
                call.enable_filter.put(True),
                call.filter_type.put(adcore.NDProcessFilterType.AVERAGE),
                call.auto_reset_filter.put(True),
                call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
                call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
            ],
        ),
        # Multiple exposures with SUM filter type
        (
            10,
            adcore.NDProcessFilterType.SUM,
            [
                call.num_filter.put(10),
                call.enable_filter.put(True),
                call.filter_type.put(adcore.NDProcessFilterType.SUM),
                call.auto_reset_filter.put(True),
                call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
                call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
            ],
        ),
        # Multiple exposures with RECURSIVE_AVG filter type
        (
            3,
            adcore.NDProcessFilterType.RECURSIVE_AVG,
            [
                call.num_filter.put(3),
                call.enable_filter.put(True),
                call.filter_type.put(adcore.NDProcessFilterType.RECURSIVE_AVG),
                call.auto_reset_filter.put(True),
                call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
                call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
            ],
        ),
        # Large number of exposures
        (
            100,
            adcore.NDProcessFilterType.AVERAGE,
            [
                call.num_filter.put(100),
                call.enable_filter.put(True),
                call.filter_type.put(adcore.NDProcessFilterType.AVERAGE),
                call.auto_reset_filter.put(True),
                call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
                call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
            ],
        ),
    ],
)
async def test_prepare_exposures_per_collection(
    process_plugin: adcore.NDProcessIO,
    exposures_per_collection,
    filter_type,
    expected_calls,
):
    await adcore.prepare_exposures_per_collection(
        process_plugin,
        exposures_per_collection=exposures_per_collection,
        filter_type=filter_type,
    )
    assert get_mock(process_plugin).mock_calls == expected_calls
