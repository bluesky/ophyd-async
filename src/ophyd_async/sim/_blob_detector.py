from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector

from ._blob_arm_logic import BlobArmLogic
from ._blob_data_logic import BlobDataLogic
from ._blob_trigger_logic import BlobTriggerLogic
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
            trigger_logic=BlobTriggerLogic(pattern_generator=self.pattern_generator),
            arm_logic=BlobArmLogic(pattern_generator=self.pattern_generator),
            data_logic=BlobDataLogic(
                path_provider=path_provider, pattern_generator=self.pattern_generator
            ),
            config_sigs=config_sigs,
            name=name,
        )
