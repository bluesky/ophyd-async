from enum import Enum

from ophyd_async.core import AsyncStatus, DetectorTrigger

from ..utils import ad_rw
from .ad_driver import ADDriver


class TriggerSource(Enum):
    freerun = "Freerun"
    line_1 = "Line1"
    line_2 = "Line2"
    fixed_rate = "FixedRate"
    software = "Software"


class TriggerMode(Enum):
    on = "On"
    off = "Off"


class ADAravisDriver(ADDriver):
    def __init__(self, prefix: str, gpio_number: int) -> None:
        self.trigger_mode = ad_rw(TriggerMode, prefix + "TriggerMode")
        self.trigger_source = ad_rw(TriggerSource, prefix + "TriggerMode")
        super().__init__(prefix)

        self.gpio_number = gpio_number
        assert gpio_number == 1 or gpio_number == 2, "invalid gpio number"
        self.TRIGGER_SOURCE = {
            DetectorTrigger.internal: TriggerSource.freerun,
            DetectorTrigger.constant_gate: TriggerSource[f"line_{self.gpio_number}"],
            DetectorTrigger.edge_trigger: TriggerSource[f"line_{self.gpio_number}"],
        }

    def set_trigger_source(self, source: DetectorTrigger) -> AsyncStatus:
        return self.trigger_source.set(self.TRIGGER_SOURCE[source])
