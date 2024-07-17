from pathlib import Path
from typing import Sequence

from ophyd_async.core import (FilenameProvider, PathProvider,
                              StaticFilenameProvider, StaticPathProvider)
from ophyd_async.core.detector import StandardDetector
from ophyd_async.protocols import AsyncReadable

from ._pattern_generator import PatternGenerator
from ._sim_pattern_detector_control import SimPatternDetectorControl
from ._sim_pattern_detector_writer import SimPatternDetectorWriter


class SimPatternDetector(StandardDetector):
    def __init__(
        self,
        path: Path,
        config_sigs: Sequence[AsyncReadable] = [],
        name: str = "",
    ) -> None:
        fp: FilenameProvider = StaticFilenameProvider(name)
        self.path_provider: PathProvider = StaticPathProvider(fp, path)
        self.pattern_generator = PatternGenerator()
        writer = SimPatternDetectorWriter(
            pattern_generator=self.pattern_generator,
            path_provider=self.path_provider,
            name_provider=lambda: self.name,
        )
        controller = SimPatternDetectorControl(
            pattern_generator=self.pattern_generator,
            path_provider=self.path_provider,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )
