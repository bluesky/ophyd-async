from ophyd_async.epics import adcore

from ._sim_io import SimDriverIO


class SimController(adcore.ADBaseController[SimDriverIO]):
    """Controller for simulated Areadetector."""

    def __init__(
        self,
        driver: SimDriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001
