from __future__ import annotations

from functools import cached_property

from ophyd_async.core import DetectorLogic, PathProvider, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector

from ._acquire_logic import PandaAcquireLogic
from ._block import CommonPandaBlocks
from ._data_logic import PandaHDFDataLogic
from ._trigger_logic import PandaTriggerLogic

MINIMUM_PANDA_IOC = "0.11.4"


class HDFPanda(CommonPandaBlocks, StandardDetector):
    """PandA with common blocks for standard HDF writing."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name: str = "",
    ):
        error_hint = f"Is PandABlocks-ioc at least version {MINIMUM_PANDA_IOC}?"
        # This has to be first so we make self.pcap
        connector = fastcs_connector(prefix, self, error_hint)
        self._logic = DetectorLogic(
            PandaTriggerLogic(self.pcap),
            PandaAcquireLogic(self.pcap),
            PandaHDFDataLogic(path_provider, self.data),
        )
        super().__init__(name=name, connector=connector)

    @cached_property
    def logic(self) -> DetectorLogic:
        return self._logic
