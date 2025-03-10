from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    wait_for_value,
)

from ._block import PcapBlock


class PandaPcapController(DetectorController):
    """For controlling a PCAP capture on the PandA."""

    def __init__(self, pcap: PcapBlock) -> None:
        self.pcap = pcap
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.000000008

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.trigger not in (
            DetectorTrigger.CONSTANT_GATE,
            DetectorTrigger.VARIABLE_GATE,
        ):
            msg = (
                "Only constant_gate and variable_gate triggering is supported on "
                "the PandA",
            )
            raise TypeError(msg)

    async def arm(self):
        self._arm_status = self.pcap.arm.set(True)
        await wait_for_value(self.pcap.active, True, timeout=1)

    async def wait_for_idle(self):
        pass

    async def disarm(self):
        await self.pcap.arm.set(False)
        await wait_for_value(self.pcap.active, False, timeout=1)
        if self._arm_status and not self._arm_status.done:
            await self._arm_status
        self._arm_status = None
