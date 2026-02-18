from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import Settings
from ophyd_async.plan_stubs import apply_settings

from ._detector import HDFPanda


@plan
def apply_panda_settings(settings: Settings[HDFPanda]) -> MsgGenerator[None]:
    """Apply given settings to a panda device."""
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)
