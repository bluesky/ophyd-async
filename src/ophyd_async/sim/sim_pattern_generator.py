from pathlib import Path
from typing import Sequence

from ophyd_async.core import (
    DeviceNameFilenameProvider,
    DirectoryProvider,
    FilenameProvider,
    StaticDirectoryProvider,
)
from ophyd_async.core.detector import StandardDetector
from ophyd_async.protocols import AsyncReadable
from ophyd_async.sim.pattern_generator import PatternGenerator

from .sim_pattern_detector_control import SimPatternDetectorControl
from .sim_pattern_detector_writer import SimPatternDetectorWriter


class SimPatternDetector(StandardDetector):
    def __init__(
        self,
        path: Path,
        config_sigs: Sequence[AsyncReadable] = [],
        name: str = "",
    ) -> None:
        fp: FilenameProvider = DeviceNameFilenameProvider()
        self.directory_provider: DirectoryProvider = StaticDirectoryProvider(fp, path)
        self.pattern_generator = PatternGenerator()
        writer = SimPatternDetectorWriter(
            pattern_generator=self.pattern_generator,
            directory_provider=self.directory_provider,
            name_provider=lambda: self.name,
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
