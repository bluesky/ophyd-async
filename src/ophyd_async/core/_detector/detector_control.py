"""Module which defines abstract classes to work with detectors"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import TypeVar, Optional

from ..async_status import AsyncStatus
from .driver import Driver

class DetectorTrigger(Enum):
    #: Detector generates internal trigger for given rate
    internal = ()
    #: Expect a series of arbitrary length trigger signals 
    edge_trigger = () 
    #: Expect a series of constant width external gate signals
    constant_gate = ()
    #: Expect a series of variable width external gate signals
    variable_gate = ()


class DetectorControl(ABC):
    @property
    @abstractmethod
    def driver(self) -> Driver:
        """The driver that actually does the data collection."""
        ...
    
    @abstractmethod 
    def get_deadtime(self, exposure: float) -> float: 
        """For a given exposure, how long should the time between exposures be""" 
  
    @abstractmethod 
    async def arm( 
        self, 
        trigger: DetectorTrigger = DetectorTrigger.internal, 
        num: int = 0, 
        exposure: Optional[float] = None, 
    ) -> AsyncStatus: 
        """Arm the detector and return AsyncStatus that waits for num frames to be written""" 
  
    @abstractmethod 
    async def disarm(self): 
        """Disarm the detector""" 


C = TypeVar("C", bound=DetectorControl)
