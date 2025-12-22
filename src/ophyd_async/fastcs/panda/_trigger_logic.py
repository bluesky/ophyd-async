from ophyd_async.core import DetectorTriggerLogic, SignalDict

from ._block import PcapBlock


class PandaTriggerLogic(DetectorTriggerLogic):
    """For controlling a PCAP capture on the PandA."""

    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    def get_deadtime(self, config_values: SignalDict) -> float:
        return 0.000000008

    async def prepare_level(self, num: int):
        pass
