from __future__ import annotations

from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import PandaArmLogic
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
        connector = fastcs_connector(self, prefix, error_hint)
        super().__init__(
            trigger_logic=PandaTriggerLogic(self.pcap),
            arm_logic=PandaArmLogic(self.pcap),
            data_logic=PandaHDFDataLogic(path_provider, self.data),
            name=name,
            connector=connector,
        )
