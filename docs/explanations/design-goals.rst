Design Goals
============


Parity with Ophyd
-----------------

It should be possible to migrate applications that use ophyd_ to ophyd-async. Meaning it must support:

- Definition of devices
- Conformity to the bluesky protocols
- Epics (ChannelAccess) as a backend

Ophyd-async should provide built-in support logic for controlling `the same set of devices as ophyd <https://blueskyproject.io/ophyd/user/reference/builtin-devices.html>`_. 


Clean Device Definition
-----------------------

It should be easy to define devices with signals that talk to multiple backends and to cleanly organize device logic via composition.

We need to be able to:

- Separate the Device interface from the multiple pieces of logic that might use that Device in a particular way
- Define that Signals of a particular type exist without creating them so backends like Tango or EPICS + PVI can fill them in


Parity with Malcolm
-------------------

.. seealso:: `./flyscanning`

Ophyd-async should provide the same building blocks for defining flyscans scans as malcolm_. It should support PandA and Zebra as timing masters by default, but also provide easy helpers for developers to write support for their own devices.

It should enable motor trajectory scanning and multiple triggering rates based around a base rate, and pausing/resuming scans. Scans should be modelled using scanspec_, which serves as a universal language for defining trajectory and time-resolved scans, and converted to the underlying format of the given motion controller. It should also be possible to define an outer scan .


Improved Trajectory Calculation
-------------------------------

Ophyd-async will provide and improve upon the algorithms that malcolm_ uses to calculate trajectories for supported hardware.

The EPICS pmac_ module supports trajectory scanning, specifying a growing array of positions, velocities and time for axes to move through to perform a scan. 
Ophyd-async will provide mechanisms for specifying these scans via a scanspec_, calculating run-ups and turnarounds based on motor parameters, keeping the trajectory scan arrays filled based on the ScanSpec, and allowing this scan to be paused and resumed.


Outstanding Design Decisions
----------------------------

To view and contribute to discussions on outstanding decisions, please see the design_ label in our Github issues.


.. _ophyd: https://github.com/bluesky/ophyd
.. _malcolm: https://github.com/dls-controls/pymalcolm
.. _scanspec: https://github.com/dls-controls/scanspec
.. _design: https://github.com/bluesky/ophyd-async/issues?q=is%3Aissue+is%3Aopen+label%3Adesign
.. _pmac: https://github.com/dls-controls/pmac
