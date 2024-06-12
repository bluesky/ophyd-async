from pathlib import Path
from typing import Sequence

from ophyd_async.core import (DirectoryProvider, StandardDetector,
                              StaticDirectoryProvider)
from ophyd_async.protocols import AsyncReadable
from ophyd_async.sim.pattern_generator import PatternGenerator

from .sim_pattern_detector_control import SimPatternDetectorControl
from .sim_pattern_detector_writer import SimPatternDetectorWriter


class SimPatternDetector(StandardDetector):
    def __init__(
        self,
        path: Path,
        config_sigs: Sequence[AsyncReadable] = [],
        name: str = "sim_pattern_detector",
    ) -> None:
        self.directory_provider: DirectoryProvider = StaticDirectoryProvider(path)
        self.pattern_generator = PatternGenerator()
        writer = SimPatternDetectorWriter(
            pattern_generator=self.pattern_generator,
            directoryProvider=self.directory_provider,
        )
        controller = SimPatternDetectorControl(
            pattern_generator=self.pattern_generator,
            directory_provider=self.directory_provider,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )
