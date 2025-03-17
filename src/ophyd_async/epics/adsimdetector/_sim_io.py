from ophyd_async.epics import adcore


class SimDriverIO(adcore.ADBaseIO):
    """Base class for driving simulated Areadetector IO.

    This mirrors the interface provided by ADSimDetector/db/simDetector.template.
    """

    pass
