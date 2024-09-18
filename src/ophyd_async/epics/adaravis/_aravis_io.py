from enum import Enum

from ophyd_async.core import SubsetEnum
from ophyd_async.epics import adcore
from ophyd_async.epics.signal import epics_signal_rw_rbv


class AravisTriggerMode(str, Enum):
    """GigEVision GenICAM standard: on=externally triggered"""

    on = "On"
    off = "Off"


"""A minimal set of TriggerSources that must be supported by the underlying record.
    To enable hardware triggered scanning, line_N must support each N in GPIO_NUMBER.
    To enable software triggered scanning, freerun must be supported.
    Other enumerated values may or may not be preset.
    To prevent requiring one Enum class per possible configuration, we set as this Enum
    but read from the underlying signal as a str.
    """
AravisTriggerSource = SubsetEnum["Freerun", "Line1"]


class AravisDriverIO(adcore.ADBaseIO):
    # If instantiating a new instance, ensure it is supported in the _deadtimes dict
    """Generic Driver supporting the Manta and Mako drivers.
    Fetches deadtime prior to use in a Streaming scan.

    Requires driver firmware up to date:
    - Model_RBV must be of the form "^(Mako|Manta) (model)$"

    This mirrors the interface provided by ADAravis/db/aravisCamera.template.
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(
            AravisTriggerMode, prefix + "TriggerMode"
        )
        self.trigger_source = epics_signal_rw_rbv(
            AravisTriggerSource,  # type: ignore
            prefix + "TriggerSource",
        )
        super().__init__(prefix, name=name)
