from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector

from ._blob_detector_controller import BlobDetectorController
from ._blob_detector_writer import BlobDetectorWriter
from ._pattern_generator import PatternGenerator


class SimBlobDetector(StandardDetector):
    """Simulates a detector and writes Blobs to file."""

    def __init__(
        self,
        path_provider: PathProvider,
        pattern_generator: PatternGenerator | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        self.pattern_generator = pattern_generator or PatternGenerator()

        super().__init__(
            controller=BlobDetectorController(
                pattern_generator=self.pattern_generator,
            ),
            writer=BlobDetectorWriter(
                pattern_generator=self.pattern_generator,
                path_provider=path_provider,
            ),
            config_sigs=config_sigs,
            name=name,
        )
