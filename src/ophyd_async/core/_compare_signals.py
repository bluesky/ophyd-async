import numpy as np

from ._table import Table


def is_same(current, required) -> bool:
    if isinstance(current, Table):
        current = current.model_dump()
        if isinstance(required, Table):
            required = required.model_dump()
        return current.keys() == required.keys() and all(
            is_same(current[k], required[k]) for k in current
        )
    elif isinstance(current, np.ndarray):
        return np.allclose(current, required)
    else:
        return current == required
