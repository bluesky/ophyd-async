from __future__ import annotations

from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector

from ._block import CommonPandaBlocks
from ._control import PandaPcapController
from ._writer import PandaHDFWriter

MINIMUM_PANDA_IOC = "0.11.4"


class HDFPanda(
    CommonPandaBlocks, StandardDetector[PandaPcapController, PandaHDFWriter]
):
    """PandA with common blocks for standard HDF writing."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        error_hint = f"Is PandABlocks-ioc at least version {MINIMUM_PANDA_IOC}?"
        # This has to be first so we make self.pcap
        connector = fastcs_connector(self, prefix, error_hint)
        controller = PandaPcapController(pcap=self.pcap)
        writer = PandaHDFWriter(
            path_provider=path_provider,
            panda_data_block=self.data,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
            connector=connector,
        )
