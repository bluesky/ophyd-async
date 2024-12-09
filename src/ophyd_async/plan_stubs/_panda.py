from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import Settings

from ._settings import apply_settings


@plan
def apply_panda_settings(settings: Settings) -> MsgGenerator[None]:
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)
