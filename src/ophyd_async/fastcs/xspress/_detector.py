from pydantic import Field, PositiveInt

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import XspressArmLogic
from ._data_logic import XspressOdinDataLogic
from ._io import XspressDetectorIO
from ._trigger_logic import XspressTriggerLogic
from ._xsp_odin_io import XspressOdinIO


class XspressTriggerInfo(TriggerInfo):
    chunk: PositiveInt = Field(default=1)


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
            XspressArmLogic(self.xspress),
            XspressOdinDataLogic(
                path_provider=path_provider,
                odin=self.od,
            ),
        )
        super().__init__(name=name, connector=connector)

    @AsyncStatus.wrap
    async def prepare(self, value: XspressTriggerInfo) -> None:
        datakey_name = self.name + self._data_logics[0].datakey_suffix

        await self.od.file_prefix.set(
            self._data_logics[0].path_provider(datakey_name).filename  # pyright: ignore[reportAttributeAccessIssue]
        )
        await self.od.fp.chunks.set(value.chunk)
        await super().prepare(value)
