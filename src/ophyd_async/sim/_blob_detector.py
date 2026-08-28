from collections.abc import Sequence
from functools import cached_property

from ophyd_async.core import (
    DetectorLogic,
    PathProvider,
    SignalR,
    StandardDetector,
)
from ophyd_async.core import StandardReadableFormat as Format

from ._blob_acquire_logic import BlobAcquireLogic
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
        for signal in config_sigs:
            self.set_readable_format(signal, Format.CONFIG_SIGNAL)
        self._logic = DetectorLogic(
            BlobTriggerLogic(pattern_generator=self.pattern_generator),
            BlobAcquireLogic(pattern_generator=self.pattern_generator),
            BlobDataLogic(
                path_provider=path_provider, pattern_generator=self.pattern_generator
            ),
            publish_collect_methods=self._publish_collect_methods,
        )
        super().__init__(name=name)

    @cached_property
    def logic(self) -> DetectorLogic:
        return self._logic
