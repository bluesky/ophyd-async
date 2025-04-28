from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo
from ophyd_async.fastcs.odin import OdinHdfIO, OdinWriter

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    _controller: EigerController
    _writer: OdinWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-01:",
        hdf_suffix="-EA-EIGER-01:OD:",
        odin_nodes: int = 4,
        name="",
    ):
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = OdinHdfIO(prefix + hdf_suffix)

        super().__init__(
            EigerController(self.drv),
            OdinWriter(
                path_provider,
                self.odin,
            ),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        await super().prepare(value)
