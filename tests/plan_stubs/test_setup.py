import pytest

from ophyd_async.plan_stubs import setup_ndstats_sum
from ophyd_async.testing import ParentOfEverythingDevice


@pytest.fixture
async def parent_device() -> ParentOfEverythingDevice:
    device = ParentOfEverythingDevice("parent")
    await device.connect(mock=True)
    return device


def test_setup_ndstats_raises_type_error(RE, parent_device: ParentOfEverythingDevice):
    detector = parent_device
    detector_name = "faulty_det"
    detector.set_name(detector_name)
    with pytest.raises(
        TypeError,
        match=(
            f"Expected {detector_name} to have 'fileio' attribute that is an "
            "NDFileHDFIO"
        ),
    ):
        RE(setup_ndstats_sum(detector))
