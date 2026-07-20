import numpy as np
import pytest

from ophyd_async.core import (
    DetectorAcquireLogic,
    DetectorTriggerLogic,
    StandardDetector,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore import (
    NDStatsTSAcquireMode,
    NDStatsTSControl,
    StatsTimeSeriesDataLogic,
    StatsTimeSeriesProvider,
)


@pytest.fixture
async def stats() -> adcore.NDStatsIO:
    async with init_devices(mock=True):
        plugin = adcore.NDStatsIO("PREFIX:STATS:")
    return plugin


async def test_prepare_bounded_sizes_and_arms_the_buffer(stats: adcore.NDStatsIO):
    logic = StatsTimeSeriesDataLogic(stats)
    provider = await logic.prepare_bounded("det-stats", num_collections=5, period=0.1)

    assert isinstance(provider, StatsTimeSeriesProvider)
    assert await stats.ts_num_points.get_value() == 5
    assert await stats.ts_acquire_mode.get_value() == NDStatsTSAcquireMode.FIXED_LENGTH
    # Erase/Start arms and clears the buffer
    assert await stats.ts_control.get_value() == NDStatsTSControl.ERASE_START
    # The datakey defaults to the Total series under the bare name
    datakeys = await provider.make_datakeys(5)
    assert list(datakeys) == ["det-stats"]
    assert datakeys["det-stats"]["shape"] == [5]
    assert logic.get_hinted_fields("det-stats") == ["det-stats"]


async def test_stop_stops_the_time_series(stats: adcore.NDStatsIO):
    logic = StatsTimeSeriesDataLogic(stats)
    await logic.stop()
    assert await stats.ts_control.get_value() == NDStatsTSControl.STOP


@pytest.mark.parametrize(
    "collections_per_event,num_events,expected",
    [
        # step scan: one event holds the whole 5-point buffer
        (5, 1, [[10.0, 11.0, 12.0, 13.0, 14.0]]),
        # fly scan: five events of one point each
        (1, 5, [[10.0], [11.0], [12.0], [13.0], [14.0]]),
    ],
)
async def test_provider_slices_array_into_events(
    stats: adcore.NDStatsIO,
    collections_per_event: int,
    num_events: int,
    expected: list[list[float]],
):
    total = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    set_mock_value(stats.ts_total, total)
    set_mock_value(stats.ts_current_point, 5)
    provider = StatsTimeSeriesProvider(
        {"det-stats": stats.ts_total}, stats.ts_current_point
    )

    pages = [
        page
        async for page in provider.make_pages(
            collections_written=5, collections_per_event=collections_per_event
        )
    ]
    (page,) = pages
    assert page["data"]["det-stats"] == expected
    assert len(page["time"]) == num_events


async def test_provider_make_readings_derives_single_reading(stats: adcore.NDStatsIO):
    """A step-scan read derives one reading holding the whole buffer."""
    total = np.array([1.0, 2.0, 3.0])
    set_mock_value(stats.ts_total, total)
    set_mock_value(stats.ts_current_point, 3)
    provider = StatsTimeSeriesProvider(
        {"det-stats": stats.ts_total}, stats.ts_current_point
    )
    readings = await provider.make_readings(collections_per_event=3)
    assert readings["det-stats"]["value"] == [1.0, 2.0, 3.0]


class _JustInternal(DetectorTriggerLogic):
    async def prepare_internal(self, num: int, livetime: float, deadtime: float): ...

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo()


class _FillStatsAcquireLogic(DetectorAcquireLogic):
    """Fills the mock time series when acquisition starts."""

    def __init__(self, stats: adcore.NDStatsIO, values: np.ndarray):
        self.stats = stats
        self.values = values

    async def start_acquiring(self):
        set_mock_value(self.stats.ts_total, self.values)
        set_mock_value(self.stats.ts_current_point, len(self.values))

    async def wait_for_idle(self): ...

    async def ensure_stopped(self): ...


async def test_step_scan_collect_pages_end_to_end(stats: adcore.NDStatsIO):
    """A writer-less detector with a stats time series emits event pages."""
    values = np.array([5.0, 6.0, 7.0, 8.0])
    det = StandardDetector(name="det")
    det.add_detector_logics(
        _JustInternal(),
        _FillStatsAcquireLogic(stats, values),
        StatsTimeSeriesDataLogic(stats),
    )
    # A bounded logic exposes collect_pages, not collect_asset_docs
    assert hasattr(det, "collect_pages")
    assert not hasattr(det, "collect_asset_docs")

    await det.stage()
    await det.prepare(TriggerInfo(collections_per_event=4))
    await det.trigger()
    pages = [page async for page in det.collect_pages()]
    (page,) = pages
    assert page["data"]["det"] == [[5.0, 6.0, 7.0, 8.0]]
    await det.unstage()
