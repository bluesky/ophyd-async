import asyncio
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from event_model import DataKey
from event_model.documents import PartialEventPage

from ophyd_async.core import (
    Array1D,
    DetectorDataLogic,
    EnableDisable,
    PageableDataProvider,
    SignalR,
    error_if_none,
    gather_dict,
)

from ._io import NDStatsIO, NDStatsTSAcquireMode, plugin_is_enabled


class StatsTimeSeriesProvider(PageableDataProvider):
    """Emits an `NDPluginStats` time series as event pages.

    The plugin holds one fixed-length array per statistic, filled by NDArray
    callbacks as the detector acquires. Progress is read from
    ``ts_current_point``, and each configured array is sliced into
    ``collections_per_event``-length chunks, one per event. The plugin's
    ``ts_timestamp`` array gives the acquisition time of each point, so the last
    point of an event supplies that event's timestamp.

    :param arrays: datakey (already suffixed) to the array signal that backs it
    :param current_point: the plugin's ``ts_current_point`` progress signal
    :param timestamps: the plugin's ``ts_timestamp`` per-point time signal
    """

    def __init__(
        self,
        arrays: Mapping[str, SignalR[Array1D[np.float64]]],
        current_point: SignalR[int],
        timestamps: SignalR[Array1D[np.float64]],
    ) -> None:
        self.arrays = dict(arrays)
        self.collections_written_signal = current_point
        self.timestamps = timestamps
        self.last_emitted = 0

    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        return {
            datakey: DataKey(
                source=signal.source,
                shape=[collections_per_event],
                dtype="array",
                dtype_numpy="<f8",
            )
            for datakey, signal in self.arrays.items()
        }

    async def make_pages(
        self, collections_written: int, collections_per_event: int
    ) -> AsyncIterator[PartialEventPage]:
        events = collections_written // collections_per_event
        if events <= self.last_emitted:
            return
        new = range(self.last_emitted, events)
        # Read every array and the per-point timestamps in one parallel batch.
        read: dict[
            SignalR[Array1D[np.float64]], Array1D[np.float64]
        ] = await gather_dict(
            {
                signal: signal.get_value()
                for signal in (*self.arrays.values(), self.timestamps)
            }
        )
        stamps = read[self.timestamps]
        # One timestamp per event: the acquisition time of that event's last point.
        event_times = [
            float(stamps[(event + 1) * collections_per_event - 1]) for event in new
        ]
        page: PartialEventPage = {
            "data": {
                datakey: [
                    list(
                        read[signal][
                            event * collections_per_event : (event + 1)
                            * collections_per_event
                        ]
                    )
                    for event in new
                ]
                for datakey, signal in self.arrays.items()
            },
            "time": event_times,
            "timestamps": dict.fromkeys(self.arrays, event_times),
        }
        self.last_emitted = events
        yield page


@dataclass
class StatsTimeSeriesDataLogic(DetectorDataLogic):
    """Bounded data logic for an `NDPluginStats` time series.

    For detectors that write no file: the stats plugin holds each statistic in a
    fixed-length buffer that must be sized before acquisition, so this is a
    data logic that emits event pages. One plugin has
    one time-series control (`ts_acquire`, `ts_num_points`) shared across many
    arrays, so one logic covers many arrays with the control embedded.

    The buffer is sized and armed in `start` by writing 1 to
    ``ts_acquire``, which erases the arrays and resets the current point before
    the detector's acquire logic drives the camera; its frames then feed the time
    series via NDArray callbacks. A detector that writes a file should pull stats
    into the file as NDAttributes instead (see `ADHDFDataLogic`).

    :param stats: the stats plugin whose time series to read
    :param stat_signals: datakey suffix to the array signal for each statistic to
        expose; defaults to the ``Total`` series under the bare datakey name
    """

    stats: NDStatsIO
    stat_signals: Sequence[tuple[str, SignalR[Array1D[np.float64]]]] = field(
        default_factory=list
    )
    datakey_suffix: str = ""
    #: Whether to switch the plugin on when starting. Left True, the plugin is
    #: enabled as part of starting. Set False to follow whatever the plugin is
    #: set to instead: a disabled plugin then makes no provider.
    enable_callbacks: bool = True
    #: What make_data_provider sized the buffer for, for start to write
    _num_collections: int | None = field(default=None, init=False, repr=False)

    def _arrays(self, datakey_name: str) -> dict[str, SignalR[Array1D[np.float64]]]:
        signals = self.stat_signals or [("", self.stats.ts_total)]
        return {datakey_name + suffix: signal for suffix, signal in signals}

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> PageableDataProvider | None:
        # The buffer is sized by count, not rate, so the period is unused.
        del period
        if num_collections == 0:
            # A finite buffer cannot serve an unbounded scan
            return None
        if not self.enable_callbacks and not await plugin_is_enabled(self.stats):
            return None
        # The datakeys are known from the arrays we were configured with, so
        # nothing has to be armed to describe them
        self._num_collections = num_collections
        return StatsTimeSeriesProvider(
            self._arrays(datakey_name),
            self.stats.ts_current_point,
            self.stats.ts_timestamp,
        )

    async def start(self) -> None:
        num_collections = error_if_none(
            self._num_collections, "make_data_provider() has not been called"
        )
        # Size the buffer and put it in fixed-length mode before arming it.
        coros: list[Awaitable] = [
            self.stats.compute_statistics.set(True),
            self.stats.ts_num_points.set(num_collections),
            self.stats.ts_acquire_mode.set(NDStatsTSAcquireMode.FIXED_LENGTH),
        ]
        if self.enable_callbacks:
            coros.append(self.stats.enable_callbacks.set(EnableDisable.ENABLE))
        await asyncio.gather(*coros)
        # Writing 1 to ts_acquire clears the arrays and resets ts_current_point to
        # 0, so the buffer is armed and empty before the detector's frames arrive.
        # This is the data logic performing the erase itself, which is why
        # trigger()'s zero baseline is correct (see ADR 0022).
        await self.stats.ts_acquire.set(True)

    async def stop(self) -> None:
        await self.stats.ts_acquire.set(False)

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return list(self._arrays(datakey_name))
