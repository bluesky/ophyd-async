from typing import Sequence
from ophyd_async.core.detector import DetectorControl, DetectorWriter, StandardDetector
from ophyd_async.core.signal import SignalR


class SimPatternDetector(StandardDetector):
    """_summary_

    Args:
        StandardDetector (_type_): _description_
    """

    def __init__(
        self,
        controller: DetectorControl,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = ...,
        name: str = "",
        writer_timeout: float = ...,
        path: str = ...,
    ) -> None:

        super().__init__(
            controller=controller,
            writer=writer,
            config_sigs=config_sigs,
            name=name,
            writer_timeout=writer_timeout,
        )

    


