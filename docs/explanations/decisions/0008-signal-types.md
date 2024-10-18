# 8. Settle on Signal Types
Date: 2024-10-18

## Status

Accepted

## Context

At present, soft Signals allow any sort of datatype, while CA, PVA, Tango restrict these to what the control system allows. This means that some soft signals when `describe()` is called on them will give `dtype=object` which is not understood by downstream tools. It also means that load/save will not necessarily understand how to serialize results. Finally we now require `dtype_numpy` for tiled, so arbitrary object types are not suitable even if they are serializable. We should restrict the datatypes allowed in Signals to objects that are serializable and are sensible to add support for in downstream tools.

## Decision

We will allow the following:
- Primitives:
    - `bool`
    - `int`
    - `float`
    - `str`
- Enums:
    - `StrictEnum` subclass which will be checked to have the same members as the CS
    - `SubsetEnum` subclass which will be checked to be a subset of the CS members
- 1D arrays:
    - `Array1D[np.bool_]`
    - `Array1D[np.int8]`
    - `Array1D[np.uint8]`
    - `Array1D[np.int16]`
    - `Array1D[np.uint16]`
    - `Array1D[np.int32]`
    - `Array1D[np.uint32]`
    - `Array1D[np.int64]`
    - `Array1D[np.uint64]`
    - `Array1D[np.float32]`
    - `Array1D[np.float64]`
    - `Sequence[str]`
    - `Sequence[MyEnum]` where `MyEnum` is a subclass of `StrictEnum` or `SubsetEnum`
- Specific structures:
    - `np.ndarray` to represent arrays where dimensionality and dtype can change and must be read from CS
    - `Table` subclass (which is a pydantic `BaseModel`) where all members are 1D arrays

## Consequences

Clients will be expected to understand:
- Python primitives (with Enums serializing as strings)
- Numpy arrays
- Pydantic BaseModels

All of the above have sensible `dtype_numpy` fields, but `Table` will give a structured row-wise `dtype_numpy`, while the data will be serialized in a column-wise fashion.
