from collections.abc import Sequence
from pathlib import Path

from ophyd_async.core import (
    FilenameProvider,
    PathProvider,
    SignalR,
    StandardDetector,
    StaticFilenameProvider,
    StaticPathProvider,
)

from ._pattern_detector_controller import PatternDetectorController
from ._pattern_detector_writer import PatternDetectorWriter
from ._pattern_generator import PatternGenerator


class PatternDetector(StandardDetector):
    def __init__(
        self,
        path: Path,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        fp: FilenameProvider = StaticFilenameProvider(name)
        self.path_provider: PathProvider = StaticPathProvider(fp, path)
        self.pattern_generator = PatternGenerator()
        writer = PatternDetectorWriter(
            pattern_generator=self.pattern_generator,
            path_provider=self.path_provider,
            name_provider=lambda: self.name,
        )
        controller = PatternDetectorController(
            pattern_generator=self.pattern_generator,
            path_provider=self.path_provider,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )
