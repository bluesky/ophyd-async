from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import Settings
from ophyd_async.fastcs.panda import SeqBlock, SeqTable
from ophyd_async.preprocessors import only_set_unequal_signals

from ._settings import apply_settings


@only_set_unequal_signals
@plan
def apply_panda_settings(settings: Settings) -> MsgGenerator[None]:
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)


def time_based_seq_settings(seq: SeqBlock) -> Settings:
    settings = Settings()
    settings[seq.table] = SeqTable.row(repeats=3)
    return settings
