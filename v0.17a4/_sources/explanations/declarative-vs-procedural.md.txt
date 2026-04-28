# Declarative vs Procedural Devices

Ophyd async has two styles of creating Devices, Declarative and Procedural. This article describes why there are two mechanisms for building Devices, and looks at the pros and cons of each style.

## Procedural style

The procedural style mirrors how you would create a traditional python class, you define an `__init__` method, add some class members, then call the superclass `__init__` method. In the case of ophyd async those class members are likely to be Signals and other Devices. For example, in the `ophyd_async.sim.SimMotor` we create its soft signal children in an `__init__` method:
```{literalinclude} ../../src/ophyd_async/sim/_motor.py
:start-after: class SimMotor
:end-before: def set_name
```
It is explicit and obvious, but verbose. It also allows you to embed arbitrary python logic in the creation of signals, so is required for making soft signals and DeviceVectors with contents based on an argument passed to `__init__`. It also allows you to use the [](#StandardReadable.add_children_as_readables) context manager which can save some typing.

## Declarative style

The declarative style mirrors how you would create a pydantic `BaseModel`. You create type hints to tell the base class what type of object you create, add annotations to tell it some parameters on how to create it, then the base class `__init__` will introspect and create them. For example, in the `ophyd_async.fastcs.panda.PulseBlock` we define the members we expect, and the baseclass will introspect the selected FastCS transport (EPICS IOC or Tango Device Server) and connect them, adding any extras that are published:
```{literalinclude} ../../src/ophyd_async/fastcs/panda/_block.py
:pyobject: PulseBlock
```
For a traditional EPICS IOC there is no such introspection mechanism, so we require a PV Suffix to be supplied via an [annotation](#typing.Annotated). For example, in `ophyd_async.epics.demo.DemoPointDetectorChannel` we describe the PV Suffix and whether the signal appears in `read()` or `read_configuration()` using [](#typing.Annotated):
```{literalinclude} ../../src/ophyd_async/epics/demo/_point_detector_channel.py
:pyobject: DemoPointDetectorChannel
```
It is compact and has the minimum amount of boilerplate, but is limited in its scope to what sorts of Signals and Devices the base class can create. It also requires the usage of a [](#StandardReadableFormat) for each Signal if using [](#StandardReadable) which may be more verbose than the procedural approach. It is best suited for introspectable FastCS and Tango devices, and repetitive EPICS Devices that are wrapped into larger Devices like areaDetectors.

## Grey area

There is quite a large segment of Devices that could be written both ways, for instance `ophyd_async.epics.demo.DemoMotor`. This could be written in either style with roughly the same legibility, so is a matter of taste:
```{literalinclude} ../../src/ophyd_async/epics/demo/_motor.py
:start-after: class DemoMotor
:end-before: def set_name
```

## Conclusion

Ophyd async supports both the declarative and procedural style, and is not prescriptive about which is used. In the end the decision is likely to come down to personal taste, and the style of the surrounding code.
