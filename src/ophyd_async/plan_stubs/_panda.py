from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import Settings
from ophyd_async.fastcs.panda import SeqBlock, SeqTable

from ._settings import apply_settings


@plan
def apply_panda_settings(settings: Settings) -> MsgGenerator[None]:
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)


# TODO: this isn't a plan stub, move to fastcs.panda
def time_based_seq_settings(seq: SeqBlock) -> Settings:
    settings = Settings()
    settings[seq.table] = SeqTable.row(repeats=3)
    return settings
