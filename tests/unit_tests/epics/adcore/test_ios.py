import pytest

from ophyd_async.core import SignalR, SignalRW, init_devices, set_mock_value
from ophyd_async.epics.adcore import NDROIStatIO, NDROIStatNIO, NDStatsIO


def test_roi_stats_channels_initialisation():
    num_channels = 5
    nd_roi_stats_io = NDROIStatIO("PREFIX:", num_channels)
    assert len(nd_roi_stats_io.channels) == num_channels
    for i in range(1, num_channels):
        assert isinstance(nd_roi_stats_io.channels[i], NDROIStatNIO)


@pytest.mark.parametrize(
    ("attribute", "suffix", "value"),
    [("centroid_x", "CentroidX_RBV", 15.25), ("centroid_y", "CentroidY_RBV", 108.625)],
)
async def test_ndstats_centroid_readback(attribute: str, suffix: str, value: float):
    async with init_devices(mock=True):
        stats = NDStatsIO("PREFIX:STATS:")

    signal = getattr(stats, attribute)
    assert isinstance(signal, SignalR)
    assert not isinstance(signal, SignalRW)
    assert signal.source == f"mock+ca://PREFIX:STATS:{suffix}"
    set_mock_value(signal, value)
    assert await signal.get_value() == value
