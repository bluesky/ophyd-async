import typing

from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import Settings

from ._settings import apply_settings

if typing.TYPE_CHECKING:
    from ophyd_async.fastcs import panda


@plan
def apply_panda_settings(settings: "Settings[panda.HDFPanda]") -> MsgGenerator[None]:
    """Apply given settings to a panda device."""
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)
