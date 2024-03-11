from typing import Sequence

from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.signal import SignalR
from ophyd_async.sim.PatternGenerator import PatternGenerator

from .SimPatternDetectorControl import SimPatternDetectorControl
from .SimPatternDetectorWriter import SimPatternDetectorWriter


class SimPatternDetector(StandardDetector):

    def __init__(
        self,
        config_sigs: Sequence[SignalR] = ...,
        name: str = "sim_pattern_detector",
        writer_timeout: float = ...,
        path: str = ...,
    ) -> None:

        pattern_generator = PatternGenerator()
        writer = SimPatternDetectorWriter(patternGenerator=pattern_generator)
        controller = SimPatternDetectorControl(patternGenerator=pattern_generator)
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
            writer_timeout=writer_timeout,
        )
