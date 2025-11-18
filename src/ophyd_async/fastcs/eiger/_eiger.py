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
        odin_writer_number: int = 1,
        name="",
    ):
        # NOTE: filename_suffix is  _000001 for the first node,
        # and when you have not rolled over the maximum number
        # of frames allowed for that node. This is an assumption
        # which is valid for b21's eigers, which only have 1 node and
        # never do more than max number of frames.

        # In cases where this assumption is no longer valid the filename_suffix
        # will need to be determined by the number of the OdinNode for each OdinNode.
        # This means that there needs to be 1 OdinWriter per OdinNode
        # see _odin_io: _odin_filename_suffix_creator
        # TODO: https://github.com/bluesky/ophyd-async/issues/1137

        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = Odin(prefix + hdf_suffix, nodes=odin_nodes)

        super().__init__(
            EigerController(self.drv),
            OdinWriter(
                path_provider,
                self.odin,
                self.drv.detector.bit_depth_image,
                plugins=plugins,
                odin_writer_number=odin_writer_number,  # see TODO
            ),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        await super().prepare(value)
