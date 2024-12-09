from collections.abc import Sequence

from ophyd_async.core import (
    PathProvider,
    SignalR,
    StandardDetector,
)

from ._pattern_detector_controller import PatternDetectorController
from ._pattern_detector_writer import PatternDetectorWriter
from ._pattern_generator import PatternGenerator


class PatternDetector(StandardDetector):
    def __init__(
        self,
        path_provider: PathProvider,
        pattern_generator: PatternGenerator | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        self.pattern_generator = pattern_generator or PatternGenerator()
        writer = PatternDetectorWriter(
            pattern_generator=self.pattern_generator,
            path_provider=path_provider,
            name_provider=lambda: self.name,
        )
        controller = PatternDetectorController(
            pattern_generator=self.pattern_generator,
            path_provider=path_provider,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )
