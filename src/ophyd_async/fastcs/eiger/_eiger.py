from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.odin._odin_io import OdinHdfIO, OdinWriter

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO


class EigerTriggerInfo(TriggerInfo):
    """Additional information required to setup triggering on an Eiger detector."""


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    _controller: EigerController
    _writer: OdinWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-01:",
        hdf_suffix="-EA-ODIN-01:",
        name="",
    ):
        connector = fastcs_connector(self, prefix)
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = OdinHdfIO(prefix + hdf_suffix + "FP:")

        super().__init__(
            EigerController(self.drv),
            OdinWriter(path_provider, lambda: self.name, self.odin),
            name=name,
            connector=connector,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: EigerTriggerInfo) -> None:  # type: ignore
        await super().prepare(value)
