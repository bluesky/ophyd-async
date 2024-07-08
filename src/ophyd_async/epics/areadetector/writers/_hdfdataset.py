from dataclasses import dataclass
from typing import Sequence


@dataclass
class _HDFDataset:
    name: str
    path: str
    shape: Sequence[int]
    dtype_str: str
    multiplier: int
