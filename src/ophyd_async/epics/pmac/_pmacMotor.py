from bluesky.protocols import Movable, Stoppable

from ophyd_async.epics.motion import Motor

from ..signal.signal import epics_signal_r


class PmacCSMotor(Motor, Movable, Stoppable):
    def __init__(self, prefix: str, name="") -> None:
        self.output_link = epics_signal_r(str, prefix + ".OUT")
        self.cs_axis = ""
        self.cs_port = ""
        super().__init__(prefix=prefix, name=name)

    async def get_cs_info(self):
        output_link = await self.output_link.get_value()
        # Split "@asyn(PORT,num)" into ["PORT", "num"]
        split = output_link.split("(")[1].rstrip(")").split(",")
        self.cs_port = split[0].strip()
        assert (
            "CS" in self.cs_port
        ), f"{self.name} not in a CS. It is not a compound motor."
        self.cs_axis = "abcuvwxyz"[int(split[1].strip()) - 1]
