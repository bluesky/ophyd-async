from collections import defaultdict

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import numpy as np
import pytest
from bluesky import RunEngine

from ophyd_async.core import (
    DetectorAcquireLogic,
    DetectorLogic,
    DetectorTriggerLogic,
    EnableDisable,
    StandardDetector,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore import (
    NDStatsTSAcquireMode,
    StatsTimeSeriesDataLogic,
    StatsTimeSeriesProvider,
)


@pytest.fixture
async def stats() -> adcore.NDStatsIO:
    async with init_devices(mock=True):
        plugin = adcore.NDStatsIO("PREFIX:STATS:")
    return plugin


async def test_start_sizes_and_arms_the_buffer(stats: adcore.NDStatsIO):
    logic = StatsTimeSeriesDataLogic(stats)
    provider = await logic.make_data_provider(
        "det-stats", num_collections=5, period=0.1
    )
    assert isinstance(provider, StatsTimeSeriesProvider)
    # Describing the buffer does not arm it
    assert await stats.ts_num_points.get_value() == 0

    await logic.start()
    assert await stats.ts_num_points.get_value() == 5
    assert await stats.ts_acquire_mode.get_value() == NDStatsTSAcquireMode.FIXED_LENGTH
    # ts_acquire=1 arms and clears the buffer
    assert await stats.ts_acquire.get_value() is True
    # The datakey defaults to the Total series under the bare name
    datakeys = await provider.make_datakeys(5)
    assert list(datakeys) == ["det-stats"]
    assert datakeys["det-stats"]["shape"] == [5]
    assert logic.get_hinted_fields("det-stats") == ["det-stats"]


async def test_unbounded_scan_makes_no_provider(stats: adcore.NDStatsIO):
    """A finite buffer cannot serve an unbounded scan, so it sits it out."""
    logic = StatsTimeSeriesDataLogic(stats)
    assert await logic.make_data_provider("det", num_collections=0, period=0.1) is None


@pytest.mark.parametrize(
    "enable_callbacks,plugin_enabled,makes_provider",
    [
        # The default switches the plugin on, whatever it was set to
        (True, EnableDisable.DISABLE, True),
        # Following the plugin, a disabled one produces nothing...
        (False, EnableDisable.DISABLE, False),
        # ...and an enabled one still works
        (False, EnableDisable.ENABLE, True),
    ],
)
async def test_follows_the_plugin_when_not_enabling_it(
    stats: adcore.NDStatsIO,
    enable_callbacks: bool,
    plugin_enabled: EnableDisable,
    makes_provider: bool,
):
    set_mock_value(stats.enable_callbacks, plugin_enabled)
    logic = StatsTimeSeriesDataLogic(stats, enable_callbacks=enable_callbacks)

    provider = await logic.make_data_provider("det", num_collections=5, period=0.1)
    assert (provider is not None) is makes_provider

    if makes_provider:
        await logic.start()
        # Only the default reaches out and switches the plugin on
        expected = EnableDisable.ENABLE if enable_callbacks else plugin_enabled
        assert await stats.enable_callbacks.get_value() is expected


async def test_stop_stops_the_time_series(stats: adcore.NDStatsIO):
    logic = StatsTimeSeriesDataLogic(stats)
    set_mock_value(stats.ts_acquire, True)
    await logic.stop()
    assert await stats.ts_acquire.get_value() is False


@pytest.mark.parametrize(
    "collections_per_event,expected_data,expected_times",
    [
        # step scan: one event holds the whole 5-point buffer, timed by its
        # last point
        (5, [[10.0, 11.0, 12.0, 13.0, 14.0]], [104.0]),
        # fly scan: five events of one point each, timed point by point
        (
            1,
            [[10.0], [11.0], [12.0], [13.0], [14.0]],
            [100.0, 101.0, 102.0, 103.0, 104.0],
        ),
    ],
)
async def test_provider_slices_array_into_events(
    stats: adcore.NDStatsIO,
    collections_per_event: int,
    expected_data: list[list[float]],
    expected_times: list[float],
):
    set_mock_value(stats.ts_total, np.array([10.0, 11.0, 12.0, 13.0, 14.0]))
    set_mock_value(stats.ts_timestamp, np.array([100.0, 101.0, 102.0, 103.0, 104.0]))
    set_mock_value(stats.ts_current_point, 5)
    provider = StatsTimeSeriesProvider(
        {"det-stats": stats.ts_total}, stats.ts_current_point, stats.ts_timestamp
    )

    pages = [
        page
        async for page in provider.make_pages(
            collections_written=5, collections_per_event=collections_per_event
        )
    ]
    (page,) = pages
    assert page["data"]["det-stats"] == expected_data
    assert page["time"] == expected_times


class _JustInternal(DetectorTriggerLogic):
    async def prepare_internal(self, num: int, livetime: float, deadtime: float): ...

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo()


class _FillStatsAcquireLogic(DetectorAcquireLogic):
    """Fills the mock time series when acquisition starts."""

    def __init__(self, stats: adcore.NDStatsIO, values: np.ndarray, times: np.ndarray):
        self.stats = stats
        self.values = values
        self.times = times

    async def start_acquiring(self):
        set_mock_value(self.stats.ts_total, self.values)
        set_mock_value(self.stats.ts_timestamp, self.times)
        set_mock_value(self.stats.ts_current_point, len(self.values))

    async def wait_for_idle(self): ...

    async def ensure_stopped(self): ...


@pytest.fixture
def stats_detector(stats: adcore.NDStatsIO) -> StandardDetector:
    """A writer-less detector whose only data logic is a stats time series."""
    values = np.array([5.0, 6.0, 7.0, 8.0])
    times = np.array([200.0, 201.0, 202.0, 203.0])
    return DetectorLogic(
        _JustInternal(),
        _FillStatsAcquireLogic(stats, values, times),
        StatsTimeSeriesDataLogic(stats),
    ).with_device("det")


def test_step_scan_through_run_engine(RE: RunEngine, stats_detector: StandardDetector):
    """A writer-less detector describes and reads as internal data.

    Driven through the RunEngine so the descriptor its datakeys make is the one
    a real scan would emit, and so has to pass event-model validation.
    """
    det = stats_detector
    docs: dict[str, list] = defaultdict(list)

    @bpp.stage_decorator([det])
    @bpp.run_decorator()
    def plan():
        # prepare() comes after stage(), which resets the detector
        yield from bps.prepare(det, TriggerInfo(collections_per_event=4), wait=True)
        yield from bps.trigger_and_read([det])

    RE(plan(), lambda name, doc: docs[name].append(doc))

    (descriptor,) = docs["descriptor"]
    assert descriptor["data_keys"]["det"]["shape"] == [4]
    assert "external" not in descriptor["data_keys"]["det"]
    (event,) = docs["event"]
    assert event["data"]["det"] == [5.0, 6.0, 7.0, 8.0]
    assert event["timestamps"]["det"] == 203.0


def test_fly_scan_emits_event_pages(RE: RunEngine, stats_detector: StandardDetector):
    """A writer-less detector collects its buffer as event pages."""
    det = stats_detector
    docs: dict[str, list] = defaultdict(list)

    @bpp.stage_decorator([det])
    @bpp.run_decorator()
    def plan():
        yield from bps.prepare(det, TriggerInfo(number_of_events=4), wait=True)
        yield from bps.declare_stream(det, name="primary")
        yield from bps.kickoff(det, wait=True)
        yield from bps.collect_while_completing(
            flyers=[det], dets=[det], flush_period=0.05
        )

    RE(plan(), lambda name, doc: docs[name].append(doc))

    (page,) = docs["event_page"]
    assert page["data"]["det"] == [[5.0], [6.0], [7.0], [8.0]]
    assert docs["stop"][0]["num_events"] == {"primary": 4}


async def test_step_scan_read_derives_single_reading(stats_detector: StandardDetector):
    """A step-scan read derives one reading holding the whole buffer, timed by
    the last point's ts_timestamp."""
    det = stats_detector
    await det.stage()
    await det.prepare(TriggerInfo(collections_per_event=4))
    await det.trigger()
    reading = await det.read()
    assert reading["det"]["value"] == [5.0, 6.0, 7.0, 8.0]
    assert reading["det"]["timestamp"] == 203.0
    await det.unstage()
