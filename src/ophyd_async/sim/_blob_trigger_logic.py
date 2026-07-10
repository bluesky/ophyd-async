from dataclasses import dataclass

from ophyd_async.core import DetectorTriggerLogic, TriggerInfo

from ._pattern_generator import PatternGenerator


@dataclass
class BlobTriggerLogic(DetectorTriggerLogic):
    pattern_generator: PatternGenerator

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.pattern_generator.setup_acquisition_parameters(
            exposure=livetime,
            period=livetime + deadtime,
            number_of_frames=num,
        )

    async def default_trigger_info(self):
        return TriggerInfo()
