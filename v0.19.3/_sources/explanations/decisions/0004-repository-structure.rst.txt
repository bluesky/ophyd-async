.. role:: bash(code)
   :language: bash

.. role:: python(code)
   :language: python

4. Repository Structure
=======================

Date: 2023-09-07

Status
------

Pending

Context
-------

This repository will be a fusion between three existing code bases; Ophyd v2, ophyd-epics-devices
and ophyd-tango-devices.

Ophyd Async has been derived from a folder originally kept in the Ophyd repository. 
Initially the structure of this folder was very simple, however it has since become quite bloated. 
In the transition to moving the v2/ folder into this repository (ophyd-async), we have decided to
structure the library in a more cohesive way, especially as this repository is now going to contain
implementation of Ophyd Async devices for EPICS and Tango control systems.

Decision
--------

This repository will be created using the python3-pip-skeleton for the Bluesky organisation.

Then, `git-filter-repo <https://github.com/newren/git-filter-repo>`_ to select commits relevant
to the following paths in the master branch of the Ophyd repository:

- .git_blame_ignore_revs
- .gitignore
- .mailmap
- .pre-commit-config.yaml
- .codecov.yml
- LICENSE
- other_licenses/
- docs/ (all folders except user_v1)
- *.* (glob pattern in root directory)
- ophyd/v2
- scripts/

These commits will be merged into the Ophyd Async repository. The same process should apply to
ophyd-epics-devices and ophyd-tango-devices, except keeping all git history in these cases.

During this process, the folder structure should incrementally be changed to
::

    ophyd-async
    ├── docs (skeleton)
    ├── LICENCE.txt
    ├── src        
    │   └── ophyd_async
    │       ├── core
    │       │   ├── __init__.py
    │       │   ├── _device
    │       │   │   ├── __init__.py
    │       │   │   ├── _backend
    │       │   │   │   ├── __init__.py
    │       │   │   │   ├── signal_backend.py
    │       │   │   │   └── sim.py
    │       │   │   ├── _signal
    │       │   │   │   ├── __init__.py
    │       │   │   │   └── signal.py
    │       │   │   ├── device_collector.py
    │       │   │   ├── device_vector.py
    │       │   │   └── ...
    │       │   ├── async_status.py
    │       │   └── utils.py
    │       ├── epics
    │       │   ├── _backend
    │       │   │   ├── __init__.py
    │       │   │   ├── _p4p.py
    │       │   │   └── _aioca.py
    │       │   ├── areadetector
    │       │   │   ├── __init__.py
    │       │   │   ├── ad_driver.py
    │       │   │   └── ...
    │       │   ├── signal
    │       │   │   └── ...
    │       │   ├── motion
    │       │   │   ├── __init__.py
    │       │   │   └── motor.py
    │       │   └── demo
    │       │       └── ...
    │       └── panda
    │           └── ...
    ├── tests
    │   ├── core
    │   │   └── ...
    │   └── epics
    └── ...

The :bash:`__init__.py` files of each submodule (core, epics, panda and eventually tango) will
be modified such that end users experience little disruption to how they use Ophyd Async.
For such users, :python:`from ophyd.v2.core import ...` can be replaced with 
:python:`from ophyd_async.core import ...`.


Consequences
------------

The git history of all three repositories being merged will be preserved, and their
code bases neatly subdivided.

Merge conflicts dealt with for ophyd-epics-devices and ophyd-tango-devices will be
clearly stated in the commit messages regarding their resolutions.
