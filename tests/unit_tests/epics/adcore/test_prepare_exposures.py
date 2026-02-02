from unittest.mock import call

import pytest

from ophyd_async.core import get_mock, init_devices
from ophyd_async.epics import adcore


@pytest.fixture
async def adbase():
    async with init_devices(mock=True):
        adbase = adcore.ADBaseIO("PREFIX:ADBASE:")
    return adbase


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
