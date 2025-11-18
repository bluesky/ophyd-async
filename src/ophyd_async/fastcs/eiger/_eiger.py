from ophyd_async.core import (
    AsyncStatus,
    PathProvider,
    StandardDetector,
    TriggerInfo,
)
from ophyd_async.epics.adcore import NDPluginBaseIO
from ophyd_async.epics.odin import Odin, OdinWriter

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
        plugins: dict[str, NDPluginBaseIO] | None = None,
        filename_suffix: str = "_000001",
        name="",
    ):
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = Odin(prefix + hdf_suffix, nodes=odin_nodes)

        super().__init__(
            EigerController(self.drv),
            OdinWriter(
                path_provider,
                self.odin,
                self.drv.detector.bit_depth_image,
                plugins=plugins,
                filename_suffix=filename_suffix,  # not shown in pv but added by odin
            ),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        await super().prepare(value)
