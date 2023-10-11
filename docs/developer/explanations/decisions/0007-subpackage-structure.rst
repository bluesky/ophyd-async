7. Sub-package Structure
========================

Date: 2023-10-11

Status
------

Accepted

Context
-------

`0004-repository-structure` proposed a top level repository structure divided into:

- `ophyd_async.core`: Core classes like ``Device``, ``Signal`` and ``AsyncStatus``
- `ophyd_async.epics`: Epics specific signals and devices
- `ophyd_async.tango`: Tango specific signals and devices
- `ophyd_async.panda`: PandA Device written on top of Epics or Tango modules

This ADR proposes a public sub-package structure. The internal private structure should be flat, but can change according to the number of classes in a public package.

Decision
--------

core
~~~~

There will be a flat public namespace under core, with contents reimported from an underscore prefixed python file. 
Suggested something like `_device.py` containing `Device` and `DeviceVector`.

epics
~~~~~

There should be an additional level of packages that correspond to the epics support module, and contain classes that map to the EPICS database and logic classes e.g.:

- ``epics.signal``: containing ``epics_signal_rw``, ``EpicsTransport``, etc.
- ``epics.ADCore``: containing ``ADDriver``, ``NDFileHDF``, ``HDFWriter`` etc. 
- ``epics.ADPilatus``: containing ``ADPilatus``, ``PilatusControl`` etc.

They can be imported from modules:

```python
from ophyd_async.epics import ADCore, ADPilatus

drv = ADPilatus.ADPilatus(prefix + "DRV:")
hdf = ADCore.NDFileHDF(prefix + "HDF:")
```

tango
~~~~~

TBC

panda
~~~~~

This should be a top level namespace containing the ``PandA``, ``SeqBlock``, ``HDFWriter``, etc.

Consequences
------------

The import paths for EPICS support modules are capitals, which is not standard, but is worth it to keep the link with the underlying support module
