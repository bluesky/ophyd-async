[![CI](https://github.com/bluesky/ophyd-async/actions/workflows/ci.yml/badge.svg)](https://github.com/bluesky/ophyd-async/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/bluesky/ophyd-async/branch/main/graph/badge.svg)](https://codecov.io/gh/bluesky/ophyd-async)
[![PyPI](https://img.shields.io/pypi/v/ophyd-async.svg)](https://pypi.org/project/ophyd-async)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

# ophyd-async

Asynchronous Bluesky hardware abstraction code, compatible with control systems like EPICS and Tango.

|    Source     |     <https://github.com/bluesky/ophyd-async>      |
| :-----------: | :-----------------------------------------------: |
|     PyPI      |             `pip install ophyd-async`             |
| Documentation |      <https://bluesky.github.io/ophyd-async>      |
|   Releases    | <https://github.com/bluesky/ophyd-async/releases> |

Ophyd-async is a Python library for asynchronously interfacing with hardware, intended to 
be used as an abstraction layer that enables experiment orchestration and data acquisition code to operate above the specifics of particular devices and control
systems.

Both ophyd and ophyd-async are typically used with the [Bluesky Run Engine][] for experiment orchestration and data acquisition.

While [EPICS][] is the most common control system layer that ophyd-async can interface with, support for other control systems like [Tango][] will be supported in the future. The focus of ophyd-async is:

* Asynchronous signal access, opening the possibility for hardware-triggered scanning (also known as fly-scanning)
* Simpler instantiation of devices (groupings of signals) with less reliance upon complex class hierarchies

[Bluesky Run Engine]: http://blueskyproject.io/bluesky
[EPICS]: http://www.aps.anl.gov/epics/
[Tango]: https://www.tango-controls.org/

<!-- README only content. Anything below this line won't be included in index.md -->

See https://bluesky.github.io/ophyd-async for more detailed documentation.
