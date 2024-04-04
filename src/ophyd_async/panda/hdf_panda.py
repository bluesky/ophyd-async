from typing import Sequence

from ophyd_async.core import DEFAULT_TIMEOUT, DetectorWriter, SignalR, StandardDetector

from .panda import PandA
from .panda_controller import PandaPcapController


class HDFPandA(PandA, StandardDetector):
    def __init__(
        self,
        prefix: str,
        controller: PandaPcapController,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        PandA.__init__(self, prefix, name=name)
        StandardDetector.__init__(
            self,
            controller,
            writer,
            config_sigs=config_sigs,
            name=name,
            writer_timeout=DEFAULT_TIMEOUT,
        )

    async def connect(
        self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
    ) -> None:

        await super().connect(sim=sim, timeout=timeout)
        self.controller.fill_blocks(self)
