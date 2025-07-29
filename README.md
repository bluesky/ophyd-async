[![CI](https://github.com/bluesky/ophyd-async/actions/workflows/ci.yml/badge.svg)](https://github.com/bluesky/ophyd-async/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/bluesky/ophyd-async/branch/main/graph/badge.svg)](https://codecov.io/gh/bluesky/ophyd-async)
[![PyPI](https://img.shields.io/pypi/v/ophyd-async.svg)](https://pypi.org/project/ophyd-async)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://choosealicense.com/licenses/bsd-3-clause)

# ![ophyd-async](https://raw.githubusercontent.com/bluesky/ophyd-async/main/docs/images/ophyd-async-logo.svg)

Asynchronous Bluesky hardware abstraction code, compatible with control systems like EPICS and Tango.

|    Source     |     <https://github.com/bluesky/ophyd-async>      |
| :-----------: | :-----------------------------------------------: |
|     PyPI      |             `pip install ophyd-async`             |
| Documentation |      <https://bluesky.github.io/ophyd-async>      |
|   Releases    | <https://github.com/bluesky/ophyd-async/releases> |

Ophyd-async is a Python library for asynchronously interfacing with hardware, intended to be used as an abstraction layer that enables experiment orchestration and data acquisition code to operate above the specifics of particular devices and control systems.

Both ophyd sync and ophyd-async are typically used with the [Bluesky Run Engine][] for experiment orchestration and data acquisition.

The main differences from ophyd sync are:

- Asynchronous Signal access, simplifying the parallel control of multiple Signals
- Support for [EPICS][] PVA and [Tango][] as well as the traditional EPICS CA
- Better library support for splitting the logic from the hardware interface to avoid complex class heirarchies

It was written with the aim of implementing fly scanning in a generic and extensible way with highly customizable devices like PandABox and the Delta Tau PMAC products. Using async code makes it possible to do the "put 3 PVs in parallel, then get from another PV" logic that is common in fly scanning without the performance and complexity overhead of multiple threads.

Devices from both ophyd sync and ophyd-async can be used in the same RunEngine and even in the same scan. This allows a per-device migration where devices are reimplemented in ophyd-async one by one.

[Bluesky Run Engine]: http://blueskyproject.io/bluesky
[EPICS]: http://www.aps.anl.gov/epics/
[Tango]: https://www.tango-controls.org/

<!-- README only content. Anything below this line won't be included in index.md -->

See https://bluesky.github.io/ophyd-async for more detailed documentation.
