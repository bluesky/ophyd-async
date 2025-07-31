from ophyd_async.core import StrictEnum


class OnState(StrictEnum):
    ON = "On"
    OFF = "Off"


class OnStateCapitalised(StrictEnum):
    ON = "ON"
    OFF = "OFF"


class EnabledState(StrictEnum):
    ENABLED = "Enabled"
    DISABLED = "Disabled"


class EnabledStateCapitalised(StrictEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class InState(StrictEnum):
    IN = "In"
    OUT = "Out"


class InStateCapitalised(StrictEnum):
    IN = "IN"
    OUT = "OUT"
