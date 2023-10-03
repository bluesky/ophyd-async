***********
Ophyd Async
***********

|build_status| |coverage| |pypi_version| |license|

ophyd-async is a Python library for asynchronously interfacing with hardware,
building upon the logic of `Ophyd`_. It is intended to be used as an
abstraction layer that enables experiment orchestration and data acquisition
code to operate above the specifics of particular devices and control systems.

Both ophyd and ophyd-async are typically used with the `Bluesky Run Engine`_ for 
experiment orchestration and data acquisition. However, these libraries are
able to be used in a stand-alone fashion.

Many facilities use ophyd-async to integrate with control systems that use 
`EPICS`_, but ophyd's design and some of its objects are also used to integrate
with other control systems.

* Put the details specific to a device or control system behind a **high-level
  interface** with methods like ``trigger()``, ``read()``, and ``set(...)``.
* **Group** individual control channels (such as EPICS V3 PVs) into logical
  "Devices" to be configured and used as units with internal coordination.
* Assign readings with **names meaningful for data analysis** that will
  propagate into metadata.
* **Categorize** readings by "kind" (primary reading, configuration,
  engineering/debugging) which can be read selectively.

============== ==============================================================
PyPI           ``pip install ophyd-async``
Source code    https://github.com/bluesky/ophyd-async
Documentation  https://blueskyproject.io/ophyd
============== ==============================================================

See the tutorials for usage examples.

.. |build_status| image:: https://github.com/bluesky/ophyd/workflows/Unit%20Tests/badge.svg?branch=master
    :target: https://github.com/bluesky/ophyd/actions?query=workflow%3A%22Unit+Tests%22
    :alt: Build Status

.. |coverage| image:: https://codecov.io/gh/bluesky/ophyd/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/bluesky/ophyd
    :alt: Test Coverage

.. |pypi_version| image:: https://img.shields.io/pypi/v/ophyd.svg
    :target: https://pypi.org/project/ophyd
    :alt: Latest PyPI version

.. |license| image:: https://img.shields.io/badge/License-BSD%203--Clause-blue.svg
    :target: https://opensource.org/licenses/BSD-3-Clause
    :alt: BSD 3-Clause License

.. _Bluesky Run Engine: http://blueskyproject.io/bluesky

.. _Ophyd: http://blueskyproject.io/ophyd

.. _EPICS: http://www.aps.anl.gov/epics/

..
    Anything below this line is used when viewing README.rst and will be replaced
    when included in index.rst

See https://blueskyproject.io/ophyd-async for more detailed documentation.
