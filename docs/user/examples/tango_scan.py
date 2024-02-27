# simple example to scan motor and acquire in each point counter value
import asyncio

from bluesky import Msg, RunEngine
from bluesky.callbacks import LiveTable
from bluesky.plans import scan

from ophyd_async.core import DeviceCollector
from ophyd_async.core.utils import merge_gathered_dicts
from ophyd_async.tango.device_controllers import (
    DGG2Timer,
    OmsVME58Motor,
    SIS3820Counter,
)

ACQUISITION_TIME = 0.1


# --------------------------------------------------------------------
async def main():
    # first, connect all necessary devices. Note, that Tango devices have to be awaited!
    async with DeviceCollector():
        omsvme58_motor = await OmsVME58Motor("p09/motor/eh.01")
        dgg2timer = await DGG2Timer("p09/dgg2/eh.01")
        sis3820 = await SIS3820Counter("p09/counter/eh.01")

    # to set acquisition time we can use set_time method of dgg2timer
    await dgg2timer.set_time(ACQUISITION_TIME)

    # create engine
    RE = RunEngine()

    # more "Blueskyisch" set of acquisition time
    RE([Msg("prepare", dgg2timer, ACQUISITION_TIME)])

    # do scan with LiveTable output
    # (seems LiveTable cannot work with async devices,
    # so we have to generate keys by ourselves...)
    dets = [omsvme58_motor, sis3820, dgg2timer]
    dets_descr = await merge_gathered_dicts([det.describe() for det in dets])
    RE(scan(dets, omsvme58_motor, 0, 1, num=11), LiveTable(list(dets_descr.keys())))


# --------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
