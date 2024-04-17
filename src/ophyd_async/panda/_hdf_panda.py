from __future__ import annotations

from typing import Sequence

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DirectoryProvider,
    SignalR,
    StandardDetector,
)
from ophyd_async.epics.pvi import create_children_from_annotations, fill_pvi_entries

from ._common_panda import CommonPandaBlocks
from ._panda_controller import PandaPcapController
from .writers._hdf_writer import PandaHDFWriter


class HDFPanda(CommonPandaBlocks, StandardDetector):
    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self._prefix = prefix

        create_children_from_annotations(self)
        controller = PandaPcapController(pcap=self.pcap)
        writer = PandaHDFWriter(
            prefix=prefix,
            directory_provider=directory_provider,
            name_provider=lambda: name,
            panda_device=self,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
            writer_timeout=DEFAULT_TIMEOUT,
        )

    async def connect(
        self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)
        await super().connect(sim=sim, timeout=timeout)
