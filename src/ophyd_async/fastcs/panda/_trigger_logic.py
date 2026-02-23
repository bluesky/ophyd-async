from ophyd_async.core import DetectorTriggerLogic, SignalDict

from ._block import PcapBlock


class PandaTriggerLogic(DetectorTriggerLogic):
    """For controlling a PCAP capture on the PandA."""

    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap

    def get_deadtime(self, config_values: SignalDict) -> float:
        # Need 1 tick of the 125MHz clock as deadtime
        # https://quantumdetectors.com/products/beamline-data-acquisition-tool/
        return 8e-9

    async def prepare_level(self, num: int):
        pass
