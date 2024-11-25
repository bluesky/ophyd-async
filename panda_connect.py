import asyncio
from pathlib import Path

import numpy as np

from ophyd_async.core import StaticFilenameProvider, StaticPathProvider
from ophyd_async.fastcs.panda import HDFPanda, SeqTable


async def get_panda():
    panda = HDFPanda(
        "PANDA1:", StaticPathProvider(StaticFilenameProvider("test-panda"), Path("."))
    )
    await panda.connect()
    assert isinstance(panda, HDFPanda)
    table = await panda.seq[1].table.get_value()
    assert isinstance(table, SeqTable)
    print("OUTA1", table.outa1)
    outa2 = table.outa2
    position = table.position
    assert isinstance(outa2, np.ndarray) and outa2.dtype == np.bool_, outa2.dtype
    assert (
        isinstance(position, np.ndarray) and position.dtype == np.int32
    ), position.dtype

    return panda


asyncio.run(get_panda())
