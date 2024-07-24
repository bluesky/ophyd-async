from pathlib import Path
from typing import Sequence

from ophyd_async.core import (
    AsyncReadable,
    FilenameProvider,
    PathProvider,
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
        config_sigs: Sequence[AsyncReadable] = [],
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
