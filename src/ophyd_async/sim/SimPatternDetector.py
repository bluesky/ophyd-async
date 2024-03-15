from pathlib import Path
from typing import Sequence

from ophyd_async.core import DirectoryProvider, StaticDirectoryProvider
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.signal import SignalR
from ophyd_async.sim.SimDriver import SimDriver

from .SimPatternDetectorControl import SimPatternDetectorControl
from .SimPatternDetectorWriter import SimPatternDetectorWriter


class SimDetector(StandardDetector):
    def __init__(
        self,
        path: Path,
        config_sigs: Sequence[SignalR] = [],
        name: str = "sim_pattern_detector",
        writer_timeout: float = 1,
    ) -> None:
        self.directory_provider: DirectoryProvider = StaticDirectoryProvider(path)
        self.pattern_generator = SimDriver()
        writer = SimPatternDetectorWriter(
            driver=self.pattern_generator,
            directoryProvider=self.directory_provider,
        )
        controller = SimPatternDetectorControl(
            driver=self.pattern_generator,
            directory_provider=self.directory_provider,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
            writer_timeout=writer_timeout,
        )
