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
from ._trigger_logic import XspressTriggerLogic
from ._xsp_odin_io import XspressOdinIO


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
            XspressOdinDataLogic(
                path_provider=path_provider,
                odin=self.od,
            ),
        )
        super().__init__(name=name, connector=connector)

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        datakey_name = self.name + self._data_logics[0].datakey_suffix

        chunk = int(1 / value.livetime) if value.livetime < 1 else 1

        await self.od.file_prefix.set(
            self._data_logics[0].path_provider(datakey_name).filename  # pyright: ignore[reportAttributeAccessIssue]
        )
        await self.od.fp.chunks.set(chunk)
        # Wait for all the datasets to have changed their chunk sizes
        await wait_for_value(self.od.fp.data_chunks_0, chunk, timeout=DEFAULT_TIMEOUT)
        await super().prepare(value)
