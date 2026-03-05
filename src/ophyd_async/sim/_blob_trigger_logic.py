from ophyd_async.core import DetectorTriggerLogic, TriggerInfo

from ._pattern_generator import PatternGenerator


class BlobTriggerLogic(DetectorTriggerLogic):
    def __init__(self, pattern_generator: PatternGenerator):
        self.pattern_generator = pattern_generator

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.pattern_generator.setup_acquisition_parameters(
            exposure=livetime,
            period=livetime + deadtime,
            number_of_frames=num,
        )

    async def default_trigger_info(self) -> TriggerInfo:
        # TODO, get the current num images
        return TriggerInfo()
