from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    PathProvider,
    StandardDetector,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.fastcs.core import fastcs_connector

from ._acquire_logic import XspressAcquireLogic
from ._data_logic import XspressOdinDataLogic
from ._io import XspressDetectorIO
from ._list_acquire_logic import XspressListAcquireLogic
from ._list_data_logic import XspressOdinListDataLogic
from ._trigger_logic import XspressTriggerLogic
from ._xsp_list_odin_io import XspressOdinListIO
from ._xsp_odin_io import XspressOdinIO


class XspressDetectorListMode(StandardDetector):
    """Ophyd-async implementation of an Xspress Detector in list mode."""

    xspress: XspressDetectorIO
    od: XspressOdinListIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        connector = fastcs_connector(prefix, self)

        self.add_detector_logics(
            XspressTriggerLogic(self.xspress),
            XspressListAcquireLogic(self.xspress, self.od),
            XspressOdinListDataLogic(
                path_provider=path_provider, odin=self.od, driver=self.xspress
            ),
        )
        super().__init__(name=name, connector=connector)

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        await self.od.fp.time_frames.set(value.number_of_events)
        await wait_for_value(
            self.od.fp.time_frames, value.number_of_events, timeout=DEFAULT_TIMEOUT
        )
        await super().prepare(value)


class XspressDetector(StandardDetector):
    """Ophyd-async implementation of an Xspress Detector."""

    xspress: XspressDetectorIO
    od: XspressOdinIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        connector = fastcs_connector(prefix, self)

        self.add_detector_logics(
            XspressTriggerLogic(self.xspress),
            XspressAcquireLogic(self.xspress),
            XspressOdinDataLogic(path_provider=path_provider, odin=self.od),
        )
        super().__init__(name=name, connector=connector)

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        chunk = int(1 / value.livetime) if value.livetime < 1 else 1
        if chunk > 4096:
            chunk = 4096
        await self.od.fp.chunks.set(chunk)
        await self.od.fp.frames.set(value.number_of_events)
        # Wait for all the datasets to have changed their chunk sizes
        await wait_for_value(self.od.fp.data_chunks_0, chunk, timeout=DEFAULT_TIMEOUT)
        await super().prepare(value)
