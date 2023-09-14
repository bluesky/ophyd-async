.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Make a Simple Device
====================

.. currentmodule:: ophyd_async.core

To make a simple device, you need to subclass from the
`StandardReadable` class, create some `Signal` instances, and optionally implement
other suitable Bluesky `Protocols <hardware_interface>` like
:class:`~bluesky.protocols.Movable`.

The rest of this guide will show examples from ``src/ophyd_async/epics/demo/__init__.py``

Readable
--------

For a simple :class:`~bluesky.protocols.Readable` object like a `Sensor`, you need to
define some signals, then tell the superclass which signals should contribute to
``read()`` and ``read_configuration()``:

.. literalinclude:: ../../../src/ophyd_async/epics/demo/__init__.py
   :pyobject: Sensor

First some Signals are constructed and stored on the Device. Each one is passed
its Python type, which could be:

- A primitive (`str`, `int`, `float`)
- An array (`numpy.typing.NDArray` or ``Sequence[str]``)
- An enum (`enum.Enum`). 

The rest of the arguments are PV connection information, in this case the PV suffix.

Finally `super().__init__() <StandardReadable>` is called with:

- Possibly empty Device ``name``: will also dash-prefix its child Device names is set
- Optional ``primary`` signal: a Signal that should be renamed to take the name
  of the Device and output at ``read()``
- ``read`` signals: Signals that should be output to ``read()`` without renaming
- ``config`` signals: Signals that should be output to ``read_configuration()``
  without renaming

All signals passed into this init method will be monitored between ``stage()``
and ``unstage()`` and their cached values returned on ``read()`` and 
``read_configuration()`` for perfomance.

Movable
-------

For a more complicated device like a `Mover`, you can still use `StandardReadable`
and implement some addition protocols:

.. literalinclude:: ../../../src/ophyd_async/epics/demo/__init__.py
   :pyobject: Mover

The ``set()`` method implements :class:`~bluesky.protocols.Movable`. This
creates a `coroutine` ``do_set()`` which gets the old position, units and
precision in parallel, sets the setpoint, then observes the readback value,
informing watchers of the progress. When it gets to the requested value it
completes. This co-routine is wrapped in a timeout handler, and passed to an
`AsyncStatus` which will start executing it as soon as the Run Engine adds a
callback to it. The ``stop()`` method then pokes a PV if the move needs to be
interrupted. 

Assembly
--------

Compound assemblies can be used to group Devices into larger logical Devices:

.. literalinclude:: ../../../src/ophyd_async/epics/demo/__init__.py
   :pyobject: SampleStage

This applies prefixes on construction:

- SampleStage is passed a prefix like ``DEVICE:``
- SampleStage.x will append its prefix ``X:`` to get ``DEVICE:X:``
- SampleStage.x.velocity will append its suffix ``Velocity`` to get
  ``DEVICE:X:Velocity``

If SampleStage is further nested in another Device another layer of prefix
nesting would occur

.. note::

   SampleStage does not pass any signals into its superclass init. This means
   that its ``read()`` method will return an empty dictionary. This means you
   can ``rd sample_stage.x``, but not ``rd sample_stage``.
