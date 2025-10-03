from ophyd_async.epics.adcore._core_io import NDROIStatIO, NDROIStatNIO  # noqa: PLC2701


def test_roi_stats_channels_initialisation():
    num_channels = 5
    nd_roi_stats_io = NDROIStatIO("PREFIX:", num_channels)
    assert len(nd_roi_stats_io.channels) == num_channels
    for i in range(1, num_channels):
        assert isinstance(nd_roi_stats_io.channels[i], NDROIStatNIO)
