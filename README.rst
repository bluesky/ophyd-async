Ophyd Async
===========

|code_ci| |docs_ci| |coverage| |pypi_version| |license|

Asynchronous device abstraction framework, building on `Ophyd`_.

============== ==============================================================
PyPI           ``pip install ophyd-async``
Source code    https://github.com/bluesky/ophyd-async
Documentation  https://blueskyproject.io/ophyd-async
============== ==============================================================

Python library for asynchronously interfacing with hardware, intended to 
be used as an abstraction layer that enables experiment orchestration and data 
acquisition code to operate above the specifics of particular devices and control
systems.

Both ophyd and ophyd-async are typically used with the `Bluesky Run Engine`_ for 
experiment orchestration and data acquisition. However, these libraries are
able to be used in a stand-alone fashion. For an example of how a facility defines
and uses ophyd-async devices, see `dls-dodal`_, which is currently using a
mixture of ophyd and ophyd-async devices.

While `EPICS`_ is the most common control system layer that ophyd-async can
interface with, other control systems like `Tango`_ are used by some facilities
also. In addition to the abstractions provided by ophyd, ophyd-async allows:

* Asynchronous signal access, opening the possibility for hardware-triggered
  scanning (also known as fly-scanning)
* Simpler instantiation of devices (groupings of signals) with less reliance
  upon complex class hierarchies

NOTE: ophyd-async is included on a provisional basis until the v1.0 release.

See the tutorials for usage examples.

.. |code_ci| image:: https://github.com/bluesky/ophyd-async/actions/workflows/code.yml/badge.svg?branch=main
    :target: https://github.com/bluesky/ophyd-async/actions/workflows/code.yml
    :alt: Code CI

.. |docs_ci| image:: https://github.com/bluesky/ophyd-async/actions/workflows/docs.yml/badge.svg?branch=main
    :target: https://github.com/bluesky/ophyd-async/actions/workflows/docs.yml
    :alt: Docs CI

.. |coverage| image:: https://codecov.io/gh/bluesky/ophyd-async/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/bluesky/ophyd-async
    :alt: Test Coverage

.. |pypi_version| image:: https://img.shields.io/pypi/v/ophyd-async.svg
    :target: https://pypi.org/project/ophyd-async
    :alt: Latest PyPI version

.. |license| image:: https://img.shields.io/badge/License-BSD%203--Clause-blue.svg
    :target: https://opensource.org/licenses/BSD-3-Clause
    :alt: BSD 3-Clause License

.. _Bluesky Run Engine: http://blueskyproject.io/bluesky

.. _Ophyd: http://blueskyproject.io/ophyd

.. _dls-dodal: https://github.com/DiamondLightSource/dodal

.. _EPICS: http://www.aps.anl.gov/epics/

.. _Tango: https://www.tango-controls.org/

..
    Anything below this line is used when viewing README.rst and will be replaced
    when included in index.rst

See https://blueskyproject.io/ophyd-async for more detailed documentation.
