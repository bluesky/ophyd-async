from unittest.mock import call

import pytest

from ophyd_async.core import EnableDisable, get_mock, init_devices, set_mock_value
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
    set_mock_value(process.filter_type, adcore.NDProcessFilterType.AVERAGE)
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
    ("exposures_per_collection", "filter_type", "expected_filter"),
    [
        # None keeps the filter type pre-configured in the IOC (AVERAGE)
        (1, None, adcore.NDProcessFilterType.AVERAGE),
        (5, adcore.NDProcessFilterType.AVERAGE, adcore.NDProcessFilterType.AVERAGE),
        (10, adcore.NDProcessFilterType.SUM, adcore.NDProcessFilterType.SUM),
        (
            3,
            adcore.NDProcessFilterType.RECURSIVE_AVG,
            adcore.NDProcessFilterType.RECURSIVE_AVG,
        ),
        (100, adcore.NDProcessFilterType.AVERAGE, adcore.NDProcessFilterType.AVERAGE),
    ],
)
async def test_prepare_filter(
    process_plugin: adcore.NDProcessIO,
    exposures_per_collection,
    filter_type,
    expected_filter,
):
    await adcore.prepare_filter(
        process_plugin,
        num_filter=exposures_per_collection,
        filter_type=filter_type,
    )
    expected_calls = [call.reset_filter.execute()]
    if filter_type is not None:
        expected_calls.append(call.filter_type.put(filter_type))
    expected_calls += [
        call.num_filter.put(exposures_per_collection),
        call.enable_filter.put(True),
        call.auto_reset_filter.put(True),
        call.data_type_out.put(adcore.ADBaseDataType.AUTOMATIC),
        call.filter_callbacks.put(adcore.NDProcessFilterCallbacks.ARRAY_N_ONLY),
        call.enable_callbacks.put(EnableDisable.ENABLE),
    ]
    assert get_mock(process_plugin).mock_calls == expected_calls
    assert await process_plugin.filter_type.get_value() == expected_filter


async def test_prepare_filter_without_plugin():
    await adcore.prepare_filter(None, num_filter=1)
    with pytest.raises(ValueError, match="Process plugin must be provided"):
        await adcore.prepare_filter(None, num_filter=2)
