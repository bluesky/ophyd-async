from __future__ import annotations

from collections.abc import Sequence

from ophyd_async.core import DEFAULT_TIMEOUT, PathProvider, SignalR, StandardDetector
from ophyd_async.epics.pvi import create_children_from_annotations, fill_pvi_entries

from ._block import CommonPandaBlocks
from ._control import PandaPcapController
from ._writer import PandaHDFWriter


class HDFPanda(CommonPandaBlocks, StandardDetector):
    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self._prefix = prefix

        create_children_from_annotations(self)
        controller = PandaPcapController(pcap=self.pcap)
        writer = PandaHDFWriter(
            prefix=prefix,
            path_provider=path_provider,
            name_provider=lambda: name,
            panda_data_block=self.data,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        # TODO: this doesn't support caching
        # https://github.com/bluesky/ophyd-async/issues/472
        await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, mock=mock)
        await super().connect(
            mock=mock, timeout=timeout, force_reconnect=force_reconnect
        )
