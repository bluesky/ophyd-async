from collections.abc import Callable

import pytest

from ophyd_async.core import (
    SignalRW,
    StaticPathProvider,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import (
    adandor,
    adaravis,
    adcore,
    adkinetix,
    admerlin,
    adpilatus,
    adsimdetector,
    advimba,
)

_DETECTOR_CLASSES = [
    adsimdetector.SimDetector,
    adandor.AndorDetector,
    adaravis.AravisDetector,
    adkinetix.KinetixDetector,
    admerlin.MerlinDetector,
    adpilatus.PilatusDetector,
    advimba.VimbaDetector,
    adcore.ContAcqDetector,
]


def _num_and_start_signals(
    det: adcore.AreaDetector,
) -> tuple[SignalRW[int], SignalRW[bool]]:
    # ContAcq buffers post_count frames per CB trigger instead of using num_images
    if isinstance(det, adcore.ContAcqDetector):
        cb = det.get_plugin("cb", adcore.NDCircularBuffIO)
        return cb.post_count, cb.trigger_
    return det.driver.num_images, det.driver.acquire


async def _make_detector(
    detector_cls: Callable[..., adcore.AreaDetector],
    path_provider: StaticPathProvider,
    proc_suffix: str | None,
) -> adcore.AreaDetector:
    async with init_devices(mock=True):
        det = detector_cls(
            "PREFIX:",
            adcore.ADWriterFactory.hdf(path_provider),
            proc_suffix=proc_suffix,
        )
    set_mock_value(det.get_plugin("hdf", adcore.NDFileHDF5IO).file_path_exists, True)
    if isinstance(det, adpilatus.PilatusDetector):
        set_mock_value(det.driver.armed, True)
    if isinstance(det, adcore.ContAcqDetector):
        set_mock_value(det.driver.image_mode, adcore.ADImageMode.CONTINUOUS)
        set_mock_value(det.driver.acquire, True)
    return det


async def _trigger_with_preserved_state(
    det: adcore.AreaDetector, expected_collections: int
) -> int:
    """Trigger, returning the first dimension of the described detector shape."""
    writer = det.get_plugin("hdf", adcore.NDFileHDF5IO)
    _, start_signal = _num_and_start_signals(det)

    def on_start(value: bool) -> bool | None:
        # stage/prepare also write False to the start signal; only count real starts
        if value:
            set_mock_value(writer.num_captured, expected_collections)
            # The CB trigger is a busy record that resets once frames are buffered
            if isinstance(det, adcore.ContAcqDetector):
                return False
        return None

    callback_on_mock_put(start_signal, on_start)
    await det.stage()
    await det.trigger()
    description = await det.describe()
    return description["det"]["shape"][0]


@pytest.fixture(autouse=True)
def preserve_detector_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")


@pytest.mark.parametrize("detector_cls", _DETECTOR_CLASSES)
@pytest.mark.parametrize("num_images, expected_collections", [(5, 5), (0, 1)])
async def test_trigger_uses_num_images_without_process_plugin(
    static_path_provider: StaticPathProvider,
    detector_cls,
    num_images: int,
    expected_collections: int,
):
    det = await _make_detector(detector_cls, static_path_provider, None)
    num_signal, _ = _num_and_start_signals(det)
    set_mock_value(num_signal, num_images)

    shape_0 = await _trigger_with_preserved_state(det, expected_collections)

    assert shape_0 == expected_collections
    assert await num_signal.get_value() == expected_collections


@pytest.mark.parametrize("detector_cls", _DETECTOR_CLASSES)
@pytest.mark.parametrize(
    "num_images, num_filter, enable_filter, expected_collections, expected_exposures",
    [
        (10, 5, True, 2, 5),
        (3, 5, True, 1, 5),  # num_images // num_filter floors to 0, clamped to 1
        (10, 5, False, 10, 1),  # num_filter ignored when filtering is disabled
    ],
)
async def test_trigger_uses_num_images_and_process_plugin(
    static_path_provider: StaticPathProvider,
    detector_cls,
    num_images: int,
    num_filter: int,
    enable_filter: bool,
    expected_collections: int,
    expected_exposures: int,
):
    det = await _make_detector(detector_cls, static_path_provider, "PROC:")
    proc = det.get_plugin("proc", adcore.NDProcessIO)
    num_signal, _ = _num_and_start_signals(det)
    set_mock_value(num_signal, num_images)
    set_mock_value(proc.num_filter, num_filter)
    set_mock_value(proc.enable_filter, enable_filter)

    shape_0 = await _trigger_with_preserved_state(det, expected_collections)

    assert shape_0 == expected_collections
    assert await proc.num_filter.get_value() == expected_exposures
    assert await num_signal.get_value() == expected_collections * expected_exposures
