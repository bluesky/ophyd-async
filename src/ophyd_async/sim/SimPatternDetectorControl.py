from ophyd_async.core.detector import DetectorControl
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorControl(DetectorControl):
    patternGenerator: PatternGenerator
    """
    
    """

    def __init__(self, patternGenerator: PatternGenerator) -> None:
        self.patternGenerator = patternGenerator
        self.patternGenerator.set_exposure(0.1)
        self.patternGenerator.write_image_to_file()
        super().__init__()
