from ._utils import StrictEnum


class OnOff(StrictEnum):
    ON = "On"
    OFF = "Off"


class EnableDisable(StrictEnum):
    ENABLE = "Enable"
    DISABLE = "Disable"


class EnabledDisabled(StrictEnum):
    ENABLED = "Enabled"
    DISABLED = "Disabled"


class InOut(StrictEnum):
    IN = "In"
    OUT = "Out"
