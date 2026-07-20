import asyncio
import time
from collections.abc import AsyncIterator, Mapping, Sequence
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
)

from ._io import NDStatsIO, NDStatsTSAcquireMode, NDStatsTSControl


class StatsTimeSeriesProvider(PageableDataProvider):
    """Emits an `NDPluginStats` time series as event pages.

    The plugin holds one fixed-length array per statistic, filled by NDArray
    callbacks as the detector acquires. Progress is read from
    ``ts_current_point``, and each configured array is sliced into
    ``collections_per_event``-length chunks, one per event.

    :param arrays: datakey (already suffixed) to the array signal that backs it
    :param current_point: the plugin's ``ts_current_point`` progress signal
    """

    def __init__(
        self,
        arrays: Mapping[str, SignalR[Array1D[np.float64]]],
        current_point: SignalR[int],
    ) -> None:
        self.arrays = dict(arrays)
        self.collections_written_signal = current_point
        self.last_emitted = 0

    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        return {
            datakey: DataKey(
                source=signal.source,
                shape=[collections_per_event],
                dtype="array",
                dtype_numpy="<f8",
                external="",
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
        # A single timestamp per event: the plugin does not expose a per-point
        # time, so use the read time.
        now = time.time()
        values = {
            datakey: await signal.get_value() for datakey, signal in self.arrays.items()
        }
        page: PartialEventPage = {
            "data": {
                datakey: [
                    list(
                        array[
                            event * collections_per_event : (event + 1)
                            * collections_per_event
                        ]
                    )
                    for event in new
                ]
                for datakey, array in values.items()
            },
            "time": [now for _ in new],
            "timestamps": {datakey: [now for _ in new] for datakey in values},
        }
        self.last_emitted = events
        yield page


@dataclass
class StatsTimeSeriesDataLogic(DetectorDataLogic):
    """Bounded data logic for an `NDPluginStats` time series.

    For detectors that write no file: the stats plugin holds each statistic in a
    fixed-length buffer that must be sized before acquisition, so this is a
    bounded (`prepare_bounded`) data logic that emits event pages. One plugin has
    one time-series control (`ts_control`, `ts_num_points`) shared across many
    arrays, so one logic covers many arrays with the control embedded.

    The buffer is sized and erased in `prepare_bounded` by writing
    ``Erase/Start`` to ``ts_control``; the detector's acquire logic then drives
    the camera as usual and its frames feed the time series via NDArray
    callbacks. A detector that writes a file should pull stats into the file as
    NDAttributes instead (see `ADHDFDataLogic`).

    :param stats: the stats plugin whose time series to read
    :param stat_signals: datakey suffix to the array signal for each statistic to
        expose; defaults to the ``Total`` series under the bare datakey name
    """

    stats: NDStatsIO
    stat_signals: Sequence[tuple[str, SignalR[Array1D[np.float64]]]] = field(
        default_factory=list
    )
    datakey_suffix: str = ""

    def _arrays(self, datakey_name: str) -> dict[str, SignalR[Array1D[np.float64]]]:
        signals = self.stat_signals or [("", self.stats.ts_total)]
        return {datakey_name + suffix: signal for suffix, signal in signals}

    async def prepare_bounded(
        self, datakey_name: str, num_collections: int, period: float
    ) -> PageableDataProvider:
        # The buffer is sized by count, not rate, so the period is unused.
        del period
        # Size the buffer and put it in fixed-length mode before arming it.
        await asyncio.gather(
            self.stats.enable_callbacks.set(EnableDisable.ENABLE),
            self.stats.compute_statistics.set(True),
            self.stats.ts_num_points.set(num_collections),
            self.stats.ts_acquire_mode.set(NDStatsTSAcquireMode.FIXED_LENGTH),
        )
        # Erase and start clears the arrays and resets ts_current_point to 0, so
        # the buffer is armed and empty before the detector's frames arrive. This
        # is the data logic performing the erase itself, which is why trigger()'s
        # zero baseline is correct (see ADR 0020).
        await self.stats.ts_control.set(NDStatsTSControl.ERASE_START)
        return StatsTimeSeriesProvider(
            self._arrays(datakey_name), self.stats.ts_current_point
        )

    async def stop(self) -> None:
        await self.stats.ts_control.set(NDStatsTSControl.STOP)

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return list(self._arrays(datakey_name))
